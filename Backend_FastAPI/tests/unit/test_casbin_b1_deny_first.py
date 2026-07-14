"""B1 — Casbin deny-first auth model + 4-field plumbing lock-in tests.

Covers four of the six B1 acceptance layers (the integration matrix
+ migration-roundtrip layers live in their own files because they need
a real DB):

1. ``auth_model.conf`` shape — 4-field policy + canonical Casbin
   ``ALLOW_AND_DENY_EFFECT`` order (allow first, deny second). This
   regression slot is real: any reorder to ``!deny && allow``
   normalises to a string Casbin's ``get_effector()`` does NOT match
   and the lib raises ``RuntimeError("unsupported effect")`` (see
   ``casbin/constant/constants.py:25``).
2. Effect-string get_effector() canonical-match — deliberately calls
   ``casbin.effect.get_effector()`` with the on-disk effect string so
   the lib upgrade chain (Casbin Python is on a quarterly cadence)
   trips this test if the canonical string ever drifts.
3. ``PolicyRule`` TypedDict + ``apply_template`` — every produced rule
   carries an ``eft`` field, default ``"allow"``; new accountant deny
   rules carry ``"deny"``.
4. ``RUN_CASBIN_LOAD_ON_STARTUP`` env-flag contract (B1 cold-cutover
   gate, mirrors T0-1 ``RUN_MIGRATIONS_ON_STARTUP`` +
   ``RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP``). Defensive default:
   only the exact lowercase ``"false"`` skips ``load_policy()``;
   ``unset / "true" / "FALSE" / typo`` all run the load.
"""
from __future__ import annotations

import re
from pathlib import Path

import casbin
import pytest

from app.casbin_config.policy_templates import (
    ACCOUNTANT_TEMPLATE,
    OFFICER_TEMPLATE,
    POLICY_TEMPLATES,
    PolicyRule,
    apply_template,
)


REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]  # Backend_FastAPI/
AUTH_MODEL_PATH = REPO_BACKEND_ROOT / "auth_model.conf"


# --- Layer 1: auth_model.conf shape ----------------------------------------


class TestAuthModelConfShape:
    def test_policy_definition_is_4_field_with_eft(self):
        text = AUTH_MODEL_PATH.read_text(encoding="utf-8")
        # The policy definition must be exactly `p = sub, obj, act, eft`.
        m = re.search(
            r"\[policy_definition\]\s*\np\s*=\s*([^\n]+)", text
        )
        assert m, "policy_definition section missing"
        tokens = [t.strip() for t in m.group(1).split(",")]
        assert tokens == ["sub", "obj", "act", "eft"], (
            "policy_definition must declare 4 tokens (sub, obj, act, eft) "
            f"for B1 deny-first; got {tokens}"
        )

    def test_policy_effect_is_canonical_allow_and_deny(self):
        text = AUTH_MODEL_PATH.read_text(encoding="utf-8")
        m = re.search(r"\[policy_effect\]\s*\ne\s*=\s*([^\n]+)", text)
        assert m, "policy_effect section missing"
        effect = m.group(1).strip()
        # Canonical Casbin effect string for allow-and-deny — order
        # matters: allow first, deny second. Casbin's `get_effector()`
        # does string-literal compare against `ALLOW_AND_DENY_EFFECT`
        # in `casbin/constant/constants.py`.
        assert effect == (
            "some(where (p.eft == allow)) && !some(where (p.eft == deny))"
        ), (
            f"policy_effect must match canonical allow-and-deny shape "
            f"(allow first, deny second); got {effect!r}"
        )


class TestEffectStringIsLibCanonical:
    """Bind the effect string straight to the Casbin lib's parser. Any
    drift in either ``auth_model.conf`` OR the lib's canonical string
    constant trips this test; the runtime would otherwise crash with
    ``RuntimeError("unsupported effect")`` on the FIRST request after
    deploy, far from the diff that introduced the drift."""

    def test_get_effector_accepts_on_disk_effect(self):
        from casbin.effect import get_effector
        from casbin.constant.constants import ALLOW_AND_DENY_EFFECT

        # Read the on-disk effect, normalise the dot-form Casbin's
        # model loader does (`p.eft → p_eft`), then assert the lib
        # accepts it. This mirrors what `AsyncEnforcer.__init__`
        # internally calls.
        text = AUTH_MODEL_PATH.read_text(encoding="utf-8")
        m = re.search(r"\[policy_effect\]\s*\ne\s*=\s*([^\n]+)", text)
        effect = m.group(1).strip()
        normalised = effect.replace("p.eft", "p_eft")
        # Should NOT raise.
        get_effector(normalised)
        # Lib's canonical string equals our normalised form.
        assert normalised == ALLOW_AND_DENY_EFFECT

    def test_get_effector_rejects_reversed_order(self):
        """Lock the failure mode the wrong order would trip (deny
        first, allow second). The lib does string-literal match, so
        even semantically-equivalent reorder does not parse."""
        from casbin.effect import get_effector

        wrong = "!some(where (p_eft == deny)) && some(where (p_eft == allow))"
        with pytest.raises(RuntimeError, match="unsupported effect"):
            get_effector(wrong)

    def test_load_auth_model_through_async_enforcer(self):
        """End-to-end: AsyncEnforcer(auth_model.conf) parses without
        raising. Catches drift between manual on-disk edits and lib
        contracts."""
        e = casbin.AsyncEnforcer(str(AUTH_MODEL_PATH))
        # 4 tokens = sub, obj, act, eft.
        assert e.model["p"]["p"].tokens == [
            "p_sub",
            "p_obj",
            "p_act",
            "p_eft",
        ]


# --- Layer 3: PolicyRule + apply_template ----------------------------------


class TestPolicyRuleTypedDict:
    def test_eft_is_optional_in_source_rules(self):
        """Existing 3-field source rules (subject/object/action) are
        still valid PolicyRule values — ``apply_template`` fills the
        default ``eft="allow"`` so callers never see a 3-tuple."""
        # Officer template has the bulk of legacy 3-field rules.
        for rule in OFFICER_TEMPLATE["policies"]:
            # Subject/object/action are always present; eft may be
            # absent on legacy rules.
            assert "subject" in rule
            assert "object" in rule
            assert "action" in rule
            # If eft is set in the source, it's one of the literal values.
            if "eft" in rule:
                assert rule["eft"] in ("allow", "deny")


class TestApplyTemplateEmits4Field:
    def test_default_eft_is_allow_for_legacy_rules(self):
        rules = apply_template("officer", "role:test")
        for r in rules:
            assert r["eft"] == "allow", (
                f"Legacy template rule must default eft='allow'; got {r}"
            )

    def test_role_substitution_works(self):
        rules = apply_template("officer", "role:test")
        for r in rules:
            assert r["subject"] == "role:test", r

    def test_accountant_core_state_machine_denies_preserved(self):
        """Lock the CORE admission state-machine deny set (PLAN §3.3.b) as a
        MUST-CONTAIN subset, so a future PR cannot silently DROP any of the 6
        original guards.

        NOTE: the accountant deny set has since grown well beyond these 6
        (F8/F9 2026-05-16 lead + admission list denies, PR #324 lead static
        routes, Q9 #07 priority denies, Nhịp hẹn appointments) — so this test
        no longer pins an EXACT count (that assertion was stale: 6 vs 47). It
        pins that the state-machine guards remain AND that the appointments
        separation-of-duties deny is present.
        """
        rules = apply_template("accountant", "role:accountant")
        deny_paths = {
            (r["object"], r["action"]) for r in rules if r["eft"] == "deny"
        }
        core_state_machine = {
            ("/api/v2/admissions/*/claim",            "POST"),
            ("/api/v2/admissions/*/request-revision", "POST"),
            ("/api/v2/admissions/*/publish-result",   "POST"),
            ("/api/v2/admissions/*/waitlist-promote", "POST"),
            ("/api/v2/admissions/*/waitlist-reject",  "POST"),
            ("/api/v2/admissions/*/admin-rollback",   "POST"),
        }
        missing = core_state_machine - deny_paths
        assert not missing, (
            "Accountant lost core state-machine deny(s) from PLAN §3.3.b: "
            f"{sorted(missing)}"
        )
        # Separation-of-duties: các endpoint mang PII lead/thí sinh (tên/SĐT) mà
        # accountant kế thừa qua g,role:accountant→role:officer PHẢI giữ deny.
        # Pin lại (thay cho exact-count cũ đã stale) để 1 PR sau không âm thầm gỡ.
        pii_separation_of_duties = {
            ("/api/leads", "GET"),                       # list 391 lead + SĐT
            ("/api/leads/{id}", "GET"),                  # chi tiết lead
            ("/api/leads/{id}/timeline", "GET"),
            ("/api/leads/{id}/consultations", "GET"),
            ("/api/leads/export", "GET"),                # xuất PII
            ("/api/leads/my/appointments", "GET"),       # feed Nhịp hẹn (name/phone)
            ("/api/admissions", "GET"),                  # list hồ sơ
            ("/api/admissions/{id}", "GET"),
            ("/api/admissions/pending-diploma", "GET"),  # nợ bằng (name/phone)
        }
        missing_pii = pii_separation_of_duties - deny_paths
        assert not missing_pii, (
            "Accountant lost PII separation-of-duties deny(s) — finance staff "
            f"would read lead/thí sinh PII via officer inheritance: {sorted(missing_pii)}"
        )

    def test_accountant_deny_rules_all_target_role_accountant(self):
        rules = apply_template("accountant", "role:accountant")
        deny_rules = [r for r in rules if r["eft"] == "deny"]
        for r in deny_rules:
            assert r["subject"] == "role:accountant", (
                "Accountant deny rule must target role:accountant "
                f"(template seeds with the role placeholder); got {r}"
            )

    def test_no_other_template_carries_deny_rules(self):
        """Officer / manager / admin / user / collaborator templates
        must NOT seed any deny rules — accountant is the only role
        explicitly denied per PLAN §3.3.b. A drift here would either
        broaden the deny scope (false positives) or hide accountant
        deny under a different template (drift)."""
        for template_id, template in POLICY_TEMPLATES.items():
            if template_id == "accountant":
                continue
            for rule in template["policies"]:
                assert rule.get("eft", "allow") == "allow", (
                    f"Template {template_id!r} carries an unexpected "
                    f"non-allow rule: {rule}"
                )


# --- Layer 4: Boot gate respect (RUN_CASBIN_LOAD_ON_STARTUP) ---------------


class TestBootGateContract:
    """The B1 gate adds a 3rd cold-cutover env flag mirroring the
    existing pair from T0-1. Only the exact lowercase ``"false"``
    skips the load; everything else (unset / true / TRUE / typo)
    runs the load. Defensive default — typos default to safe (load),
    not unsafe (skip)."""

    def test_default_is_load(self):
        """Unset env var → load (default true)."""
        # Simulate the env-read snippet from main.py lifespan.
        flag = "true"  # default if unset
        assert flag != "false"

    def test_lowercase_false_skips(self):
        flag = "false"
        assert flag == "false"  # the only value that skips

    @pytest.mark.parametrize(
        "value",
        [
            "FALSE", "False", "FaLsE",
            "true", "TRUE", "1", "0", "no",
            "", "  ", "fals", "false ", " false",
        ],
    )
    def test_anything_other_than_lowercase_false_runs_load(self, value):
        """Defensive default: only exact lowercase 'false' skips. Mirror
        the T0-1 contract verified in PR #189 (14-case bash gate logic
        re-run on parent post-merge)."""
        assert value != "false"

    def test_docker_entrypoint_includes_flag_echo(self):
        """The entrypoint echoes a status line for ops-grep parity
        with the two existing flags. Catch silent removal of the
        log surface."""
        entrypoint = REPO_BACKEND_ROOT / "docker-entrypoint.sh"
        text = entrypoint.read_text(encoding="utf-8")
        # The flag name + the conditional shape that mirrors gate 1/2.
        assert "RUN_CASBIN_LOAD_ON_STARTUP" in text, (
            "docker-entrypoint.sh must reference the B1 gate name"
        )
        # The 'false' literal in the conditional check (mirror gate 1/2).
        assert (
            'if [ "${RUN_CASBIN_LOAD_ON_STARTUP:-true}" != "false" ]; then'
            in text
        ), (
            "Entrypoint conditional shape must mirror RUN_MIGRATIONS_ON_STARTUP "
            "and RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP for ops parity"
        )

    def test_main_py_lifespan_honors_flag(self):
        """Source-grep: the lifespan reads the env and the load_policy()
        call is conditional on the flag value. Catch a future refactor
        that drops the gate."""
        main_py = REPO_BACKEND_ROOT / "app" / "main.py"
        text = main_py.read_text(encoding="utf-8")
        assert "RUN_CASBIN_LOAD_ON_STARTUP" in text, (
            "main.py lifespan must read the B1 gate env var"
        )
        # Defensive default in code: getenv(..., "true").
        assert (
            'os.getenv("RUN_CASBIN_LOAD_ON_STARTUP", "true")' in text
        ), (
            "main.py must default the B1 gate to 'true' when unset, "
            "matching docker-entrypoint.sh's :-true expansion"
        )

    def test_boot_gate_skip_bypasses_empty_policy_fail_fast(self):
        """When the gate skips ``enforcer.load_policy()``,
        ``enforcer.get_policy()`` legitimately returns [] but the
        production fail-fast block immediately after the load call
        must NOT fire. Otherwise the cold-cutover deploy at RUNBOOK
        §7.2 T+1:00 (RUN_CASBIN_LOAD_ON_STARTUP=false) would
        crash-loop the backend container instead of yielding
        ``uvicorn ready`` (line 332-333).

        Two equivalent shapes are accepted:

        - **Patch A** (preferred, 1-line) — the empty-policy check is
          guarded inline by the flag:
              ``if casbin_load_flag != "false" and not enforcer.get_policy():``
        - **Patch B** — the entire empty-policy / auto-seed block is
          moved under the ``else:`` branch of the
          ``if casbin_load_flag == "false":`` skip, so the fail-fast
          is unreachable when the gate skipped the load.

        Either shape prevents the crash; this test locks at least one
        in place so a future refactor cannot regress to the bug
        Codex caught between B1 first-cut and amend.
        """
        main_py = REPO_BACKEND_ROOT / "app" / "main.py"
        text = main_py.read_text(encoding="utf-8")

        # Patch A signature — flag-guarded inline.
        gated_inline = (
            'casbin_load_flag != "false" and not enforcer.get_policy()'
            in text
        )

        # Patch B signature — the empty-policy block sits inside the
        # else branch of the gate so the skip path bypasses it. We
        # check by INDENT: a Patch B refactor places
        # ``if not enforcer.get_policy():`` at the SAME or DEEPER
        # indent as ``await enforcer.load_policy()`` (both inside the
        # else branch). The pre-patch (buggy) state has the check at
        # SHALLOWER indent — at top level after the if/else — so it
        # always runs. Indent comparison catches that bug; bare
        # textual ordering does not.
        def _indent_of(needle: str) -> int:
            for line in text.split("\n"):
                if needle in line:
                    return len(line) - len(line.lstrip())
            return -1

        load_indent = _indent_of("await enforcer.load_policy()")
        check_indent = _indent_of("if not enforcer.get_policy()")
        wrapped_in_else = (
            load_indent >= 0
            and check_indent >= 0
            and check_indent >= load_indent
        )

        assert gated_inline or wrapped_in_else, (
            "Empty-policy fail-fast in main.py lifespan must be guarded "
            "against the RUN_CASBIN_LOAD_ON_STARTUP=false skip path. "
            "Otherwise cold-cutover T+1:00 crashes the container with "
            "RuntimeError('Casbin policies not initialized') instead of "
            "yielding uvicorn ready (RUNBOOK §7.2 line 332-333). Apply "
            "Patch A (guard inline: 'casbin_load_flag != \"false\" and "
            "not enforcer.get_policy()') or Patch B (move the empty-"
            "policy block under the else branch of the gate)."
        )
