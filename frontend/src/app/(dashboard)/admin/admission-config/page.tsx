/**
 * Admission Configuration Page
 *
 * Main orchestrator for the admission configuration console
 * Manages Phase 1 (Master Data), Phase 2 (Programs), and Phase 3 (Config)
 */

import { Suspense } from "react";
import { AdmissionConfigClient } from "./_components/AdmissionConfigClient";
import AdmissionConfigLoading from "./loading";

export default function AdmissionConfigPage() {
  return (
    <Suspense fallback={<AdmissionConfigLoading />}>
      <AdmissionConfigClient />
    </Suspense>
  );
}
