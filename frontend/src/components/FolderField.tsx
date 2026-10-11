// A folder path typed in, or chosen with the folder dialog when the app has one (window mode).
import { api, AppInfo } from "../api";

export default function FolderField(props: { value: string; onChange: (v: string) => void; info: AppInfo | null; label: string }) {
  async function browse() {
    const { path } = await api.pickFolder();
    if (path) props.onChange(path);
  }
  return (
    <label className="field">
      <span>{props.label}</span>
      <span className="row">
        <input
          value={props.value}
          onChange={(e) => props.onChange(e.target.value)}
          placeholder="/path/to/the/page/images"
          required
        />
        {props.info?.can_pick_folder && (
          <button type="button" onClick={browse}>
            Browse…
          </button>
        )}
      </span>
    </label>
  );
}
