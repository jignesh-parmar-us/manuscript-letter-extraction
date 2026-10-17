// The one way the screens talk to the backend (app/api.py).
//
// Every request carries the session token that the backend wrote into the page
// (window.__TOKEN__). Image URLs from the backend already contain it.
// A failed request throws ApiError with the backend's message (`detail`) and, for
// "needs confirmation" answers, code = "needs_confirmation" (status 409).

declare global {
  interface Window {
    __TOKEN__?: string;
  }
}

export function token(): string {
  return window.__TOKEN__ ?? new URLSearchParams(window.location.search).get("token") ?? "";
}

export class ApiError extends Error {
  status: number;
  code?: string;
  constructor(status: number, message: string, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
  get needsConfirmation(): boolean {
    return this.status === 409 && this.code === "needs_confirmation";
  }
}

type Method = "GET" | "POST" | "PATCH" | "PUT" | "DELETE";

/** `body`: sent as JSON, or as it is when it is a file (an upload, C21). */
export async function request<T>(method: Method, path: string, body?: unknown): Promise<T> {
  const raw = body instanceof Blob;
  const response = await fetch(path, {
    method,
    headers: {
      "X-Token": token(),
      ...(body !== undefined ? { "Content-Type": raw ? "application/octet-stream" : "application/json" } : {}),
    },
    body: body === undefined ? undefined : raw ? (body as Blob) : JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = response.statusText || `Error ${response.status}`;
    let code: string | undefined;
    try {
      const data = await response.json();
      if (typeof data.detail === "string") detail = data.detail;
      else if (Array.isArray(data.detail)) detail = data.detail.map((d: { msg: string }) => d.msg).join("; ");
      code = data.code;
    } catch {
      // not JSON: keep the status text
    }
    throw new ApiError(response.status, detail, code);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const get = <T>(path: string) => request<T>("GET", path);
export const post = <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {});
export const patch = <T>(path: string, body: unknown) => request<T>("PATCH", path, body);
export const put = <T>(path: string, body: unknown) => request<T>("PUT", path, body);
export const del = <T>(path: string) => request<T>("DELETE", path);

/** One page (`&page_id=`), some pages (`&page_ids=1,2`), or nothing (every page). */
function pagesQuery(pages?: number | number[]): string {
  if (typeof pages === "number") return pages ? `&page_id=${pages}` : "";
  return pages?.length ? `&page_ids=${pages.join(",")}` : "";
}

// ---- types of the backend's answers ---------------------------------------------------------

export interface AppInfo {
  version: string;
  library: string;
  mode: "window" | "browser";
  can_pick_folder: boolean;
  uploads?: string; // where uploaded pages are kept (C20, C21)
}

/** How a book is written. Printed books can be read by Tesseract to suggest labels (Phase 2);
 *  handwritten books learn from the books already labelled. */
export type Writing = "handwritten" | "printed";

export const WRITING_LABEL: Record<Writing, string> = { handwritten: "Handwritten", printed: "Printed" };

export type Part = "training" | "read"; // the two parts of a book (C16a): Training Data, Read Book

/** What a library row is (Phase 3, C20): a dataset (Training Data: cut, grouped, reviewed, labelled) or a book
 *  (Read Book: read). A book learns from the datasets of its reading model (`datasets`, C23). */
export type Kind = "dataset" | "book";

export const KIND_LABEL: Record<Kind, string> = { dataset: "Dataset", book: "Book" };

export interface BookSummary {
  id: number;
  name: string;
  kind: Kind;
  datasets?: { id: number; name: string }[]; // a book: the datasets its reading model learns from (C23)
  used_by: { id: number; name: string }[]; // a dataset: the books that learn from it
  reading_model_id?: number | null; // a book: its reading model (C23)
  input_dir: string;
  writing: Writing;
  read_dir: string; // Read Book: a folder of images, or...
  read_pdf: string; // ...the name of the uploaded PDF (its pages are images in the book folder)
  read_pages: number; // Read Book pages cut
  reviewed: number; // letters in reviewed groups
  reader_id: number | null; // the book's active letter reader (C14)
  pages: number; // Training Data pages
  samples: number;
  groups: number;
  labelled: number;
  unsure: number;
  created_at: string | null;
  updated_at: string | null;
  captured_at: string | null;
}

export interface Book extends BookSummary {
  settings: Record<string, unknown>;
  undo: number;
  redo: number;
  job: Job | null;
  ocr_runs?: { engine: Engine; finished_at: string | null; result: Record<string, number | string[]> }[]; // C11, C13
}

export interface JobPage {
  file: string;
  status: string;
  message: string;
  seconds: number;
}

export interface Job {
  id: string;
  book_id: number;
  kind: "capture" | "add_pages" | "recut_page" | "export" | "suggest" | "fix_cuts" | "fix_bars" | "capture_read" | "import_pdf"
    | "copy_pages"
    | "convert" | "line_search" | "line_search_train" | "line_search_measure" | "train" | "use_reader" | "generate_letters"
    | "top_up";
  status: "running" | "done" | "failed" | "cancelled";
  done: number;
  total: number;
  current: string;
  pages: JobPage[];
  result: Record<string, unknown> | null;
  error: string;
  seconds: number;
}

export interface PageProblem {
  file: string;
  problem: "missing" | "changed" | "new";
}

export interface PageInfo {
  id: number;
  file: string;
  width: number;
  height: number;
  status: string;
  message: string;
  lines: number;
  samples: number;
  image: string;
  part?: Part;
  number?: number; // its place in the book
  excluded?: boolean; // C22: listed only when asked for
}

/** A page of the page manager (C22): a page prepared or captured (`id`), an exclusion of a file not prepared
 *  yet (`id`, not `prepared`), or an image file not prepared yet (no `id`, status "new"). */
export interface PageEntry {
  id: number | null;
  file: string;
  number: number | null;
  excluded: boolean;
  prepared: boolean;
  status: string;
  message: string;
  lines: number;
  samples: number;
  checked: number;      // checked lines (Line truth)
  corrections: number;  // corrected or reviewed whole lines, proofread lines
  reviewed: number;     // letters in reviewed groups
  missing: boolean;     // the image file is not in the folder
  thumb: string;
}

export interface PageList {
  part: Part;
  folder: string;
  owned: boolean;       // the images are the app's own copies (uploaded, or a PDF's pages): deleting removes them
  pages: PageEntry[];
}

/** How uncertain letters are written in downloads: [?], [?ક] (the best guess inside), or the plain guess. */
export type Marker = "mark" | "guess" | "none";

/** One letter of a converted page (C16b). */
export interface TextLetter {
  sample_id: number;
  box: [number, number, number, number];
  text_dev: string; // "" when no reader could read it
  text_guj: string;
  conf: number; // 0 to 1
  // who read it: "both" (Tesseract and the groups), "tesseract+reader", "reader+groups", ... ; "label": corrected by you (C17)
  source: string;
  uncertain: boolean;
  space: boolean; // a word gap before it (printed books)
  image?: string | null; // the letter's picture
  read_dev?: string; // what the conversion read, where you corrected it
  lm_from?: string; // what the readers read, where the language model changed it (C15)
  readings: [string, string, number][]; // (reader, text, score) seen
  // Tesseract's reading alone, for "Tesseract only" (printed books)
  t_text_dev?: string;
  t_text_guj?: string;
  t_conf?: number;
  t_uncertain?: boolean;
}

/** Which readers the Text view shows: Tesseract's reading alone, or with the labelled groups' opinion. */
export type Readers = "tesseract" | "both";
/** What the downloads write: the cut-letter text (Readers) or lines read whole, with or without the language model. */
export type TextSource = Readers | "lines" | "lines_lm" | "search";

/** Who read the lines whole: Tesseract, or the line search (our reader). */
export type LineEngine = "tesseract" | "search";

export interface PageText {
  page_id: number;
  text_dev: string;
  text_guj: string;
  lines: TextLetter[][];
  uncertain: number;
  uncertain_tesseract?: number;
  readers: string;
  converted_at: string | null;
  // proofreading (C17)
  line_states?: ("" | "proofread" | "changed")[]; // per line; "changed": edited since it was proofread
  proofread?: number;
  corrected?: number;
  edited_at?: string | null;
}

export interface TextSummary {
  page_id: number;
  uncertain: number;
  proofread?: number;
  lines?: number;
  converted_at: string | null;
}

/** A line read whole by Tesseract (no letter cutting), with the language model's corrections. */
export interface WholeAkshara {
  text_dev: string;
  text_guj: string;
  conf: number | null; // 0 to 100; null for our reader
  space: boolean; // a word gap before it
  uncertain: boolean;
  lm_dev?: string; // the language model's reading, where it differs
  lm_guj?: string;
  search_dev?: string; // the line search's reading, where it differs ("" where it read nothing)
  search_guj?: string;
  other_dev?: string; // our reader's view: Tesseract's reading, where it differs ("" where it read nothing)
  other_guj?: string;
  box?: [number, number, number, number] | null; // on the page
}

export interface WholeLine {
  line_id: number;
  number: number;
  box: [number, number, number, number];
  text_dev: string;
  text_guj: string;
  aksharas: WholeAkshara[];
  edited_dev?: string; // your correction ("" when none)
  edited_guj?: string;
  reviewed?: boolean;
  searched?: boolean; // the line search (our reader) read it
  image?: string | null; // the line image: only this line's ink
  image_box?: [number, number, number, number]; // where it lies on the page
}

export interface WholeLines {
  page_id: number;
  lines: WholeLine[];
  uncertain: number;
  read_at: string | null;
}

/** Our reader (the line search): what it was trained on, its last fold-fair measure and its last quick one. */
export interface LineSearchState {
  reader: { letters: number; labels: number; lines: number; trained_at: string; seconds: number; changed: boolean } | null;
  measure: LineSearchMeasure | null;
  quick_measure?: LineSearchMeasure | null; // 2 of the 4 folds: for screening only, never a result
}

export interface LineSearchMeasure {
  measured_at: string;
  folds: number;
  quick?: boolean;
  tested_folds?: number; // the folds read: all, or 2 of 4 when quick
  pages: number;
  lines: number;
  chars: number;
  cer: { ours: number; tesseract: number; tesseract_lm: number }; // % of the characters wrong
  marked: number; // % of the aksharas marked by the second opinion
  mistakes: number; // aksharas still wrong after Tesseract + language model
  caught: number; // of them marked
  line_results: {
    page: string;
    line: number;
    truth: string;
    ours: string;
    tesseract: string;
    tesseract_lm: string;
    chars: number;
    wrong: { ours: number; tesseract: number; tesseract_lm: number };
  }[];
}

/** Read Book → Reading setup (C23): the book's reading model, the datasets it learns from, its reader. */
export interface ReadingSetupInfo {
  model: { id: number; name: string; folder: string } | null;
  writing: Writing;
  datasets: BookSummary[];
  others: BookSummary[]; // the datasets not chosen, to add
  reader: LineSearchState["reader"];
  measure: LineSearchMeasure | null;
  quick_measure: LineSearchMeasure | null;
}

/** The line truth screen: checked text of whole lines. */
export interface TruthProgress {
  pages: { page_id: number; file: string; lines: number; checked: number }[];
  lines: number;
  checked: number;
}

export interface TruthLine {
  line_id: number;
  number: number;
  box: [number, number, number, number];
  image: string;
  truth_dev: string | null; // null: not checked yet
  truth_guj: string | null;
}

/** An imported text file the language model learns from (C15). */
export interface WordListInfo {
  id: number;
  name: string;
  file: string;
  lines: number;
  aksharas: number;
  books: number[]; // the books that use it
  created_at: string | null;
}

/** What a book's language model learns from (C15). */
export interface BookLanguage {
  enabled: boolean;
  labels: { stretches: number; aksharas: number };
  proofread: { lines: number; aksharas: number };
  lists: WordListInfo[];
  aksharas: number; // all together
}

export interface ProofreadStats {
  lines: number;
  chars: number;
  cer: number | null; // share of characters the conversion read wrong on proofread lines
  cer_tesseract: number | null;
}

/** A group is "system generated" while all its letters were made by the system; reviewed or not, until a
 * real letter joins it. */
export const isGenerated = (g: Group): boolean => g.samples > 0 && g.generated === g.samples;

export interface Group {
  id: number;
  code: string;
  kind: "letter" | "danda" | "digit";
  label_dev: string;
  label_guj: string;
  status: "auto" | "reviewed" | "labelled";
  locked: boolean;
  samples: number;
  red: number;
  black: number;
  generated: number; // letters made by the system from parts of others ("Generate missing letters")
  spread: number | null;
  example_id: number | null;
  example_image: string | null;
  updated_at: string | null;
  suggestion: LabelSuggestion | null; // voted from the samples' readings (C11, C13)
  other_suggestion?: LabelSuggestion | null; // the other reader's suggestion, when it differs (C13)
  readings: Reading[]; // the 3 most common OCR readings of its samples; two strong ones = a mixed group
  read: number; // samples with an OCR reading
}

/** A label suggested for a group by a reader (C11: Tesseract). Accepting it is a normal label action. */
export interface LabelSuggestion {
  label_dev: string;
  label_guj: string;
  share: number; // weighted share of the winning reading, 0 to 1
  count: number; // samples read as it
  read: number; // samples read
  engine: Engine;
  agree?: Engine[]; // both readers suggest this label (C13)
  merge_into: { id: number; code: string } | null; // another group already has this label
}

/** Who reads the letters: Tesseract (C11) or the labelled groups of other books (C13). */
export type Engine = "tesseract" | "books" | "reader";

export const ENGINE_NAME: Record<Engine, string> = {
  tesseract: "Tesseract",
  books: "your labelled books",
  reader: "your letter checker",
};

/** A trained letter reader (C14). */
export interface ReaderInfo {
  id: number;
  name: string;
  kind: string;
  created_at: string | null;
  trained_on: {
    books?: number[];
    book_names?: string[];
    letters?: number;
    labels?: number;
    min_samples?: number;
    include_unreviewed?: boolean;
    include_words?: boolean;
    left_out?: [string, number][];
    test_pages?: number;
    test_letters?: number;
  };
  accuracy: number | null; // on the test pages
  accuracy_20: number | null; // labels with 20 or more letters
  labels: number;
  per_label?: { label: string; letters: number; tested: number; accuracy: number | null }[];
  confusions?: [string, string, number][];
  check?: number;
  seconds?: number;
}

/** A letter the active reader is sure belongs to another label than its group's. */
export interface CheckItem {
  sample_id: number;
  group_id: number;
  group_code: string;
  label: string;
  read: string;
  label_guj: string;
  read_guj: string;
  prob: number;
  reviewed: boolean;
  locked: boolean; // its group is locked: unlock it to move the letter
  sample: Sample;
}

/** Another book whose labelled groups can suggest labels here (C13). */
export interface ReferenceBook {
  id: number;
  name: string;
  writing: Writing;
  labelled: number;
  comparable: boolean; // same fingerprint settings: its letters can be compared with this book's
  default: boolean; // comparable and the same writing: used unless others are chosen
}

/** Whether Tesseract can run with the book's languages (GET /api/tesseract). */
export interface TesseractStatus {
  ok: boolean;
  error?: string;
  version?: string;
  langs_needed: string;
}

/** Suggestions compared with the user's labels: each labelled group voted as if unlabelled (C12). */
export interface SuggestionAccuracy {
  engine: Engine | null;
  labelled: number;
  suggested: number;
  right: number;
  none: number;
  bands: { band: string; right: number; wrong: number }[];
  wrong: { label: string; suggested: string; groups: number }[];
}

export interface Reading {
  label_dev: string;
  label_guj: string;
  count: number;
}

export interface Suggestion {
  group_id: number;
  code: string;
  label_dev: string;
  label_guj: string;
  distance: number;
}

export interface Sample {
  id: number;
  page_id: number | null;
  page_file: string | null; // file name of its page (null for uploaded samples)
  line: number;
  pos: number;
  box: [number, number, number, number];
  ink: "red" | "black";
  kind: string;
  source: string;
  group_id: number | null;
  distance: number | null;
  deleted: boolean;
  rules: string;
  image: string;
  context?: string | null; // the sample on its line with its neighbours (null for uploaded samples)
  suggestion?: Suggestion | null;
  // its own OCR reading (C11): for unsure samples only confident ones on printed books; in groups all of them
  reading?: { label_dev: string; label_guj: string; confidence: number; engine: Engine } | null;
}

export interface SamplePage {
  total: number;
  offset: number;
  samples: Sample[];
}

/** Every action answers with what it did and the new undo / redo counts. */
export interface ActionResult {
  kind?: string;
  group_id?: number;
  undo: number;
  redo: number;
  [key: string]: unknown;
}

export interface LabelInfo {
  ok: boolean;
  error?: string;
  devanagari?: string;
  gujarati?: string;
  code_points_devanagari?: string;
  code_points_gujarati?: string;
  category?: string;
  kept_in_devanagari?: string[];
  letters?: number; // aksharas: 1 for a letter, more for a word
  used_by?: LabelUser[]; // groups of the book that have this label (when asked with a book)
}

export interface LabelUser {
  id: number;
  code: string;
  locked: boolean;
  samples: number;
}

export interface HistoryItem {
  id: number;
  kind: string;
  undone: boolean;
  created_at: string;
  [key: string]: unknown;
}

export interface LineInfo {
  id: number;
  number: number;
  box: [number, number, number, number];
  ink: string;
  image: string;
}

export interface PageDetail {
  id: number;
  book_id: number;
  file: string;
  width: number;
  height: number;
  status: string;
  message: string;
  line_spacing: number;
  image: string;
  part?: Part;
  lines: LineInfo[];
  samples: Sample[];
}

/** One of the library's fonts to show the text in (custom fonts, T1): an upload or a Font Maker font. */
export interface DisplayFont {
  id: string;
  name: string;
  source: "upload" | "fontmaker";
  family: string;              // the family name inside the font (used in Word files)
  scripts: ("gujarati" | "devanagari")[];
  chars: string;               // its Gujarati and Devanagari characters
  embeddable: boolean;         // may be embedded in a Word file
  joins: boolean;              // has OpenType rules to join conjuncts (some Apple fonts have only Apple's own)
  size: number;                // your size (A- / A+), times the size matched to the normal fonts; 1 = as matched
  added_at: string | null;
  version: number;
}

/** A font built in Font Maker, to add as a tab. */
export interface FontMakerFont {
  project: string;
  name: string;
  build: string;
  built_at: string;
  added: boolean;
}

export interface NewSampleResult extends ActionResult {
  sample?: { id: number; page_id: number | null; box: number[]; source: string };
  samples?: { id: number }[];
  overlapping?: number[];
}

// ---- calls ----------------------------------------------------------------------------------

export const api = {
  app: () => get<AppInfo>("/api/app"),
  chooseLibrary: (path: string) => post<{ library: string; restart_needed: boolean }>("/api/app/library", { path }),
  pickFolder: () => post<{ path: string | null }>("/api/app/pick-folder"),
  chooseUploads: (path: string) => post<{ uploads: string }>("/api/app/uploads", { path }),
  openHelp: (page: string) => post<{ opened: string }>("/api/app/open-help", { page }),

  books: () => get<BookSummary[]>("/api/books"),
  datasets: () => get<BookSummary[]>("/api/datasets"),
  /** A dataset or a book (C20: the routes of what both have answer under /api/books for either). */
  book: (id: number) => get<Book>(`/api/books/${id}`),
  createDataset: (name: string, writing: Writing) => post<Book>("/api/datasets", { name, writing }),
  createBook: (name: string, writing: Writing, datasetId: number | null = null) =>
    post<Book>("/api/books", { name, writing, dataset_id: datasetId }),
  setInputFolder: (id: number, path: string) => post<Book>(`/api/datasets/${id}/folder`, { path }),
  /** One page image or PDF uploaded into a dataset or a book (C21); a PDF answers with the job that turns it
   *  into page images. */
  uploadPage: (kind: Kind, id: number, file: File) =>
    request<{ book: Book | null; job: Job | null }>("POST",
      `/api/${kind === "book" ? "books" : "datasets"}/${id}/upload?name=${encodeURIComponent(file.name)}`, file),
  /** A folder's page images copied into a dataset's upload folder (a job, C21). */
  copyFolder: (id: number, path: string) => post<Job>(`/api/datasets/${id}/copy-folder`, { path }),
  renameBook: (id: number, name: string) => patch<Book>(`/api/books/${id}`, { name }),
  setWriting: (id: number, writing: Writing) => patch<Book>(`/api/books/${id}`, { writing }),
  suggest: (id: number) => post<Job>(`/api/datasets/${id}/suggest`, { engine: "tesseract" }),
  fixCuts: (id: number) => post<Job>(`/api/datasets/${id}/fix-cuts`),
  fixBars: (id: number) => post<Job>(`/api/datasets/${id}/fix-bars`),
  generateLetters: (id: number) => post<Job>(`/api/datasets/${id}/generate-letters`),
  topUp: (id: number) => post<Job>(`/api/datasets/${id}/top-up`),
  tesseract: (bookId: number) => get<TesseractStatus>(`/api/tesseract?book_id=${bookId}`),
  accuracy: (bookId: number, engine?: Engine) =>
    get<SuggestionAccuracy>(`/api/datasets/${bookId}/suggestion-accuracy${engine ? `?engine=${engine}` : ""}`),
  referenceBooks: (bookId: number) => get<ReferenceBook[]>(`/api/datasets/${bookId}/reference-books`),
  suggestBooks: (id: number, books: number[] | null) =>
    post<Job>(`/api/datasets/${id}/suggest`, { engine: "books", books }),
  deleteBook: (id: number) => del<void>(`/api/books/${id}`),
  setSettings: (id: number, settings: Record<string, unknown> | null) =>
    patch<Book>(`/api/books/${id}/settings`, { settings }),
  pageProblems: (id: number, part: Part = "training") => get<PageProblem[]>(`/api/books/${id}/page-problems?part=${part}`),
  pages: (id: number, part: Part = "training") => get<PageInfo[]>(`/api/books/${id}/pages?part=${part}`),
  pageList: (id: number) => get<PageList>(`/api/books/${id}/page-list`),
  excludePage: (id: number, file: string, excluded: boolean, force = false) =>
    post<{ file: string; excluded: boolean }>(`/api/books/${id}/page-list/exclude`, { file, excluded, force }),
  deletePage: (id: number, file: string, force = false) =>
    post<{ file: string; file_removed: boolean; excluded: boolean }>(`/api/books/${id}/page-list/delete`, { file, force }),
  movePage: (id: number, pageId: number, by: number) =>
    post<{ page: number; number: number }>(`/api/books/${id}/pages/${pageId}/move`, { by }),
  readFolder: (id: number, path: string, force = false) => post<Book>(`/api/books/${id}/read/folder`, { path, force }),
  readPdf: (id: number, path: string, force = false) => post<Job>(`/api/books/${id}/read/pdf`, { path, force }),
  readCapture: (id: number) => post<Job>(`/api/books/${id}/read/capture`),
  train: (id: number, opts: { books?: number[]; min_samples: number; include_unreviewed: boolean; include_words: boolean; name?: string }) =>
    post<Job>(`/api/datasets/${id}/train`, opts),
  readers: () => get<ReaderInfo[]>("/api/readers"),
  reader: (readerId: number) => get<ReaderInfo>(`/api/readers/${readerId}`),
  deleteReader: (readerId: number) => del<void>(`/api/readers/${readerId}`),
  useReader: (id: number, readerId: number | null) => post<Job>(`/api/datasets/${id}/reader`, { reader_id: readerId }),
  checkThese: (id: number) => get<CheckItem[]>(`/api/datasets/${id}/check`),
  confirmSamples: (id: number, sampleIds: number[], ok = true) =>
    post<{ confirmed: number }>(`/api/datasets/${id}/check/confirm`, { sample_ids: sampleIds, ok }),
  convert: (id: number, pageIds?: number[], mode: "letters" | "lines" = "letters") =>
    post<Job>(`/api/books/${id}/convert`, { page_ids: pageIds ?? null, part: "read", mode }),
  lineSearch: (id: number, pageIds?: number[], retrain = false) =>
    post<Job>(`/api/books/${id}/line-search`, { page_ids: pageIds ?? null, part: "read", retrain }),
  lineSearchReader: (id: number) => get<LineSearchState>(`/api/books/${id}/line-search`),
  lineSearchMeasure: (id: number, quick = false) =>
    post<Job>(`/api/books/${id}/line-search/measure${quick ? "?quick=true" : ""}`, {}),
  lineSearchTrain: (id: number) => post<Job>(`/api/books/${id}/line-search/train`, {}),
  readingSetup: (id: number) => get<ReadingSetupInfo>(`/api/books/${id}/reading-setup`),
  setBookDatasets: (id: number, datasetIds: number[]) =>
    put<ReadingSetupInfo>(`/api/books/${id}/datasets`, { dataset_ids: datasetIds }),
  wholeLines: (pageId: number, engine: LineEngine = "tesseract") =>
    get<WholeLines>(`/api/pages/${pageId}/whole-lines?engine=${engine}`),
  saveWholeLine: (lineId: number, change: { text?: string; reviewed?: boolean; shown?: string }) =>
    put<{ line_id: number; edited_dev: string; edited_guj: string; reviewed: boolean }>(`/api/lines/${lineId}/whole`, change),
  bookWholeLines: (id: number, engine: LineEngine = "tesseract") =>
    get<{ page_id: number; lines: number }[]>(`/api/books/${id}/whole-lines?engine=${engine}`),
  pageText: (pageId: number) => get<PageText>(`/api/pages/${pageId}/text`),
  bookTexts: (id: number) => get<TextSummary[]>(`/api/books/${id}/texts`),
  proofread: (pageId: number, line: number, proofread = true) =>
    post<PageText>(`/api/pages/${pageId}/proofread`, { line, proofread }),
  proofreadStats: (bookId: number) => get<ProofreadStats>(`/api/books/${bookId}/proofread-stats`),
  // the line truth screen
  truthProgress: (bookId: number) => get<TruthProgress>(`/api/books/${bookId}/truth`),
  truthLines: (pageId: number) => get<TruthLine[]>(`/api/pages/${pageId}/truth`),
  lineTesseract: (lineId: number) =>
    get<{ line_id: number; text_dev: string; text_guj: string }>(`/api/lines/${lineId}/tesseract`),
  saveTruth: (lineId: number, text: string, tesseract = "") =>
    put<{ line_id: number; truth_dev: string | null; truth_guj: string | null }>(`/api/lines/${lineId}/truth`, {
      text,
      tesseract,
    }),
  // the language model (C15)
  bookLanguage: (bookId: number) => get<BookLanguage>(`/api/books/${bookId}/language`),
  wordLists: () => get<WordListInfo[]>("/api/wordlists"),
  importWordList: (path: string, name: string, bookId: number) =>
    post<WordListInfo>("/api/wordlists", { path, name, book_id: bookId }),
  useWordList: (id: number, bookId: number, use: boolean) =>
    patch<WordListInfo>(`/api/wordlists/${id}`, { book_id: bookId, use }),
  deleteWordList: (id: number) => del<void>(`/api/wordlists/${id}`),
  /** The text of one page, of some pages (the ticked ones, C19; none: every page) or of the whole part.
   *  `font`: one of the library's fonts (custom fonts, T3), set and embedded in a Word file; `scale`: its size
   *  against the normal fonts', applied to the Word file's font size. */
  textUrl: (id: number, format: "txt" | "docx", script: "gujarati" | "devanagari", marker: Marker, readers: TextSource,
    pages?: number | number[], font?: string | null, scale = 1) =>
    `/files/texts/${id}?format=${format}&script=${script}&marker=${marker}&readers=${readers}${pagesQuery(pages)}${format === "docx" && font ? `&font=${encodeURIComponent(font)}${scale !== 1 ? `&scale=${scale}` : ""}` : ""}&token=${encodeURIComponent(token())}`,
  // the library's fonts to show the text in (custom fonts, T1)
  fonts: () => get<DisplayFont[]>("/api/fonts"),
  uploadFont: (file: File) => post<DisplayFont>(`/api/fonts/upload?name=${encodeURIComponent(file.name)}`, file),
  fontMakerFonts: () => get<FontMakerFont[]>("/api/fonts/fontmaker"),
  addFontMakerFont: (project: string) => post<DisplayFont>("/api/fonts/fontmaker", { project }),
  removeFont: (id: string) => del<void>(`/api/fonts/${encodeURIComponent(id)}`),
  setFontSize: (id: string, size: number) => patch<DisplayFont>(`/api/fonts/${encodeURIComponent(id)}`, { size }),
  /** The font file (`version` changes when a Font Maker font is built again, so the browser loads it anew). */
  fontUrl: (id: string, version: number) =>
    `/files/fonts/${encodeURIComponent(id)}?v=${version}&token=${encodeURIComponent(token())}`,
  /** The page images (not the text) of one page, of some pages or of every Read Book page, as one PDF. */
  pageImagesUrl: (id: number, pages?: number | number[]) =>
    `/files/page-images/${id}?part=read${pagesQuery(pages)}&token=${encodeURIComponent(token())}`,

  capture: (id: number, force = false) => post<Job>(`/api/datasets/${id}/capture`, { force }),
  addPages: (id: number) => post<Job>(`/api/datasets/${id}/add-pages`),
  recutPage: (id: number, pageId: number, force = false) =>
    post<Job>(`/api/books/${id}/pages/${pageId}/recut`, { force }),
  job: (jobId: string) => get<Job>(`/api/jobs/${jobId}`),
  cancelJob: (jobId: string) => post<Job>(`/api/jobs/${jobId}/cancel`),

  // review (C5e)
  groups: (bookId: number) => get<Group[]>(`/api/datasets/${bookId}/groups`),
  group: (groupId: number) => get<Group>(`/api/groups/${groupId}`),
  groupSamples: (groupId: number, offset = 0, limit = 200) =>
    get<SamplePage>(`/api/groups/${groupId}/samples?offset=${offset}&limit=${limit}`),
  unsure: (bookId: number, offset = 0, limit = 200) =>
    get<SamplePage>(`/api/datasets/${bookId}/unsure?offset=${offset}&limit=${limit}`),
  deleted: (bookId: number, offset = 0, limit = 200) =>
    get<SamplePage>(`/api/datasets/${bookId}/unsure?deleted=true&suggest=false&offset=${offset}&limit=${limit}`),
  move: (bookId: number, sampleIds: number[], groupId: number | null) =>
    post<ActionResult>(`/api/datasets/${bookId}/actions/move`, { sample_ids: sampleIds, group_id: groupId }),
  newGroup: (bookId: number, sampleIds: number[]) =>
    post<ActionResult>(`/api/datasets/${bookId}/actions/new-group`, { sample_ids: sampleIds }),
  merge: (bookId: number, targetId: number, sourceIds: number[]) =>
    post<ActionResult>(`/api/datasets/${bookId}/actions/merge`, { target_id: targetId, source_ids: sourceIds }),
  dissolve: (bookId: number, groupId: number) =>
    post<ActionResult>(`/api/datasets/${bookId}/actions/dissolve`, { group_id: groupId }),
  label: (bookId: number, groupId: number, text: string) =>
    post<ActionResult>(`/api/datasets/${bookId}/actions/label`, { group_id: groupId, text }),
  variants: (bookId: number, groupId: number) =>
    post<ActionResult>(`/api/datasets/${bookId}/actions/variants`, { group_id: groupId }),
  status: (bookId: number, groupId: number, change: { reviewed?: boolean; locked?: boolean }) =>
    post<ActionResult>(`/api/datasets/${bookId}/actions/status`, { group_id: groupId, ...change }),
  deleteSamples: (bookId: number, sampleIds: number[]) =>
    post<ActionResult>(`/api/books/${bookId}/actions/delete`, { sample_ids: sampleIds }),
  restoreSamples: (bookId: number, sampleIds: number[]) =>
    post<ActionResult>(`/api/books/${bookId}/actions/restore`, { sample_ids: sampleIds }),
  // label suggestions (C12)
  acceptSuggestions: (bookId: number, items: { group_id: number; label_dev: string }[]) =>
    post<ActionResult>(`/api/datasets/${bookId}/actions/accept-suggestions`, { items }),
  rejectSuggestion: (bookId: number, groupId: number, labelDev: string) =>
    post<ActionResult>(`/api/datasets/${bookId}/actions/reject-suggestion`, { group_id: groupId, label_dev: labelDev }),
  labelSamples: (bookId: number, sampleIds: number[], text: string) =>
    post<ActionResult>(`/api/books/${bookId}/actions/label-samples`, { sample_ids: sampleIds, text }),
  splitMixed: (bookId: number) => post<ActionResult>(`/api/datasets/${bookId}/actions/split-mixed`),
  removeReadings: (bookId: number, sampleIds: number[]) =>
    post<ActionResult>(`/api/datasets/${bookId}/actions/remove-readings`, { sample_ids: sampleIds }),
  readAs: (groupId: number, text: string) =>
    get<{ ids: number[] }>(`/api/groups/${groupId}/read-as?text=${encodeURIComponent(text)}`),
  undo: (bookId: number) => post<ActionResult>(`/api/books/${bookId}/undo`),
  redo: (bookId: number) => post<ActionResult>(`/api/books/${bookId}/redo`),
  history: (bookId: number) => get<HistoryItem[]>(`/api/books/${bookId}/history`),
  // fixing cuts and adding samples (C5f)
  page: (pageId: number) => get<PageDetail>(`/api/pages/${pageId}`),
  crop: (bookId: number, pageId: number, box: [number, number, number, number]) =>
    post<NewSampleResult>(`/api/books/${bookId}/samples/crop`, { page_id: pageId, box }),
  join: (bookId: number, sampleIds: number[]) =>
    post<NewSampleResult>(`/api/books/${bookId}/samples/join`, { sample_ids: sampleIds }),
  split: (bookId: number, sampleId: number, x: number) =>
    post<NewSampleResult>(`/api/books/${bookId}/samples/split`, { sample_id: sampleId, x }),
  upload: (bookId: number, filename: string, data: string) =>
    post<NewSampleResult>(`/api/datasets/${bookId}/samples/upload`, { filename, data }),

  // export (C5g)
  exportBook: (bookId: number, folder: string | null, image: string | null) =>
    post<Job>(`/api/datasets/${bookId}/export`, { folder, image }),
  openFolder: (path: string) => post<{ opened: string }>("/api/app/open-folder", { path }),

  checkLabel: (text: string, bookId?: number) =>
    get<LabelInfo>(`/api/label?text=${encodeURIComponent(text)}${bookId ? `&book_id=${bookId}` : ""}`),
};

/** Local date and time of a timestamp from the backend (stored in UTC). */
export function localTime(iso: string | null | undefined): string {
  if (!iso) return "–";
  return new Date(iso).toLocaleString();
}

/** The contents of a file as base64 (for uploads). */
export async function fileToBase64(file: Blob): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}
