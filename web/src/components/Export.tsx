import type { RunView } from "../state";
import { exportUrl } from "../api";

export default function Export({ v, runId }: { v: RunView; runId: string }) {
  if (!v.theory && !v.playbook) return null;
  return (
    <div className="export-row">
      {v.theory && <a className="btn" href={exportUrl(runId, "manual.md")} download>manual.md</a>}
      {v.playbook && <a className="btn" href={exportUrl(runId, "controller.py")} download>controller.py</a>}
    </div>
  );
}
