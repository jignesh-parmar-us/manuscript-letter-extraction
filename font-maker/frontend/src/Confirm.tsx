// A small "Are you sure?" dialog (a copy of the reading app's components/Confirm.tsx: the two screens
// do not share code, see font-maker/docs/FONT_PLAN.md section 1). Use it like:
//   const [dialog, confirm] = useConfirm();
//   if (await confirm("Delete this font?", "Delete")) { ... }
import { ReactElement, useCallback, useState } from "react";
import { createPortal } from "react-dom";

interface Pending {
  message: string;
  okLabel: string;
  resolve: (ok: boolean) => void;
}

export function useConfirm(): [ReactElement | null, (message: string, okLabel?: string) => Promise<boolean>] {
  const [pending, setPending] = useState<Pending | null>(null);
  const confirm = useCallback(
    (message: string, okLabel = "OK") =>
      new Promise<boolean>((resolve) => setPending({ message, okLabel, resolve })),
    [],
  );
  const answer = (ok: boolean) => {
    pending?.resolve(ok);
    setPending(null);
  };
  const dialog = pending
    ? createPortal(
        <div className="backdrop">
          <div className="dialog" role="dialog" aria-modal="true">
            <p>{pending.message}</p>
            <div className="row end">
              <button onClick={() => answer(false)}>Cancel</button>
              <button className="primary" onClick={() => answer(true)} autoFocus>
                {pending.okLabel}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )
    : null;
  return [dialog, confirm];
}
