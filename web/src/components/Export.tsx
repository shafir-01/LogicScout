import type { RunView } from "../state";
import { exportUrl } from "../api";

export default function Export({ v, runId }: { v: RunView; runId: string }) {
  if (!v.theory && !v.playbook) return null;
  return (
    <div className="export">
      <h3 className="label">Take it with you</h3>
      <div className="export-row">
        {v.theory && <a className="btn" href={exportUrl(runId, "manual.md")} download title="The rules it learned, in plain English">Download manual</a>}
        {v.playbook && <a className="btn" href={exportUrl(runId, "controller.py")} download title="A standalone controller. No model needed">Download controller</a>}
      </div>
    </div>
  );
}
