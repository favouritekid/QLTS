/**
 * GĐ2-B F3 — nút "Kiểm hồ sơ" (E6) + theo dõi lượt kiểm (E7 / E8). Nửa giao diện của HĐ5: client xử lý cả 202 `done` (GĐ2-B chạy
 * đồng bộ) lẫn 202 `queued` / `running` (GĐ2-C có thể chạy nền).
 *
 * Luồng (thiết kế §3.5 + đính chính 1 §5 "F3" + đính chính 2 §1; pha / chuyển pha là hàm THUẦN ở `lib/review-sessions/run-tracking.ts`):
 *  - bấm: nhớ mốc `latest_run.id` của E3 đang xem; gửi `{kind: "evaluate", session_version}` (thời gian chờ riêng > 60 s ở API);
 *  - 202: đối chiếu `Location` (lệch ⇒ lỗi hợp đồng, không theo dõi); `done` ⇒ mở M5 theo `id`; `failed` ⇒ hiện mã; còn lại ⇒ hỏi E8
 *    với nhịp giãn dần, DỪNG khi xong / hỏng / lỗi / hết trần;
 *  - mất kết nối / 502 / 504 / hết thời gian chờ ⇒ tra E7 trang 1 NGAY: có lượt mới hơn mốc ⇒ theo dõi lượt ấy; không ⇒ cho bấm lại;
 *  - 409 `REVIEW_RUN_IN_PROGRESS` ⇒ KHÔNG gửi lại E6; hỏi E7 (giãn dần) tới khi lượt mới hơn mốc kết thúc, hoặc tới TRẦN ⇒ "Lượt
 *    của người khác chưa xong — thử lại sau.";
 *  - một lần hỏi lỗi (kể cả 429) ⇒ DỪNG tự hỏi, hiện lỗi, KHÔNG vẽ trạng thái cũ; "Kiểm tra lại" mở cửa sổ mới.
 *
 * E7 / E8 ở đây gọi THẲNG hàm API (không qua bộ đệm React Query) ⇒ mỗi lần hỏi là một lần đọc máy chủ, không bao giờ vẽ dữ liệu
 * đệm (chặt hơn `staleTime 0 / gcTime 0` của DC-1). Làm mới E2 / E3 / E7 / E8 / E10: sau E6 KẾT THÚC (hook `useCreateReviewRun`,
 * `onSettled`, bất kể kết quả) và LẠI MỘT LẦN khi lượt theo dõi kết thúc qua một lần hỏi lại (lượt vừa xong đổi `latest_run`).
 *
 * Trạng thái theo dõi nằm ở thành phần GỌI hook này (màn chi tiết lần xét, khai TRƯỚC mọi nhánh dữ liệu / lỗi của E3 — khuôn
 * F01-4) ⇒ E3 tải lại lỗi (nhánh lỗi) không làm mất / dừng việc theo dõi.
 */
import { useEffect, useRef, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"

import { getReviewRun, listReviewRuns, reviewRunLocationPath } from "@/lib/api/review-sessions"
import { describeReviewSessionError } from "@/lib/review-sessions/messages"
import {
  IDLE_PHASE,
  RUN_POLL_PLAN,
  isSettledPhase,
  locationMatches,
  phaseAfterCreateError,
  phaseAfterCreated,
  phaseAfterListPoll,
  phaseAfterPollError,
  phaseAfterRunPoll,
  phaseForRetry,
  type RunTrackPhase,
} from "@/lib/review-sessions/run-tracking"
import { LIST_PAGE_SIZE_DEFAULT } from "@/lib/zod/review-sessions"

import { refreshAfterReviewWrite, useCreateReviewRun } from "./use-review-sessions"

export interface ReviewRunTracker {
  phase: RunTrackPhase
  /** Bấm "Kiểm hồ sơ": `sessionVersion` = `version` của E3 đang xem; `baselineRunId` = `latest_run.id` của E3 (mốc). */
  start: (sessionVersion: number, baselineRunId: number | null) => void
  /** "Kiểm tra lại" sau lỗi hỏi lại / sau trần. */
  retry: () => void
}

/** `onDone(runId)`: lượt của lần bấm này đã `done` ⇒ màn mở M5 của lượt ấy. */
export function useReviewRunTracker(sessionId: number, onDone: (runId: number) => void): ReviewRunTracker {
  const queryClient = useQueryClient()
  const create = useCreateReviewRun(sessionId)
  const [phase, setPhase] = useState<RunTrackPhase>(IDLE_PHASE)
  const onDoneRef = useRef(onDone)
  useEffect(() => {
    onDoneRef.current = onDone
  }, [onDone])

  // Một lần hỏi cho mỗi pha "polling" (pha đổi ⇒ hẹn lần kế; rời màn / pha đổi giữa chừng ⇒ huỷ hẹn + huỷ request).
  useEffect(() => {
    if (phase.kind !== "polling") return
    const current = phase
    const controller = new AbortController()
    const timer = setTimeout(() => {
      void (async () => {
        let next: RunTrackPhase
        try {
          const runId = current.target.runId
          if (current.target.mode === "mine" && runId !== null) {
            next = phaseAfterRunPoll(current, await getReviewRun(sessionId, runId, controller.signal), RUN_POLL_PLAN)
          } else {
            const page = await listReviewRuns(sessionId, { page: 1, page_size: LIST_PAGE_SIZE_DEFAULT }, controller.signal)
            next = phaseAfterListPoll(current, page, RUN_POLL_PLAN)
          }
        } catch (error) {
          if (controller.signal.aborted) return
          setPhase(phaseAfterPollError(current, describeReviewSessionError(error, "read")))
          return
        }
        if (controller.signal.aborted) return
        setPhase(next)
        if (isSettledPhase(next)) refreshAfterReviewWrite(queryClient, sessionId)
        if (next.kind === "done") onDoneRef.current(next.runId)
      })()
    }, current.delayMs)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [phase, queryClient, sessionId])

  const start = (sessionVersion: number, baselineRunId: number | null) => {
    setPhase({ kind: "submitting" })
    create.mutate(
      { kind: "evaluate", session_version: sessionVersion },
      {
        onSuccess: ({ run, location }) => {
          const next = phaseAfterCreated(
            run,
            locationMatches(location, reviewRunLocationPath(sessionId, run.id)),
            RUN_POLL_PLAN,
          )
          setPhase(next)
          if (next.kind === "done") onDoneRef.current(next.runId)
        },
        onError: (error) => {
          setPhase(phaseAfterCreateError(describeReviewSessionError(error, "write"), baselineRunId, RUN_POLL_PLAN))
        },
      },
    )
  }

  const retry = () => {
    if (phase.kind === "poll_error" || phase.kind === "ceiling") setPhase(phaseForRetry(phase.target))
  }

  return { phase, start, retry }
}
