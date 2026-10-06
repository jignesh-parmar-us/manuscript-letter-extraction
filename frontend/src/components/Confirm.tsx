// A small "Are you sure?" dialog. Use it like:
//   const [dialog, confirm] = useConfirm();
//   if (await confirm("Delete this book?", "Delete")) { ... }
//   return <>{dialog} ...</>;
// The dialog is drawn into <body> (a portal), so it lies above everything even when it is opened
// from inside a sticky or positioned part of the page, such as the Review tab's side bar.
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
  const dialog = pending ? createPortal(
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
  ) : null;
  return [dialog, confirm];
}
