// Shows an error from the backend (or anything else) above a screen, with a close button.
export default function ErrorBox({ error, onClose }: { error: unknown; onClose?: () => void }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="error" role="alert">
      <span>{message}</span>
      {onClose && (
        <button className="link" onClick={onClose} aria-label="Close">
          ×
        </button>
      )}
    </div>
  );
}
