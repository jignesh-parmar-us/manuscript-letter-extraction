// A small "Are you sure?" dialog. Use it like:
//   const [dialog, confirm] = useConfirm();
//   if (await confirm("Delete this book?", "Delete")) { ... }
//   return <>{dialog} ...</>;
import { ReactElement, useCallback, useState } from "react";

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
  const dialog = pending ? (
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
    </div>
  ) : null;
  return [dialog, confirm];
}
