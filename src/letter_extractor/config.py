"""All thresholds and defaults in one place (tunable without touching the code).

A JSON file passed with --config overrides any value, for example
    {"black_max_rel_l": 0.6, "red": {"min_speck_px": 4}}
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class InkParams:
    """Settings that differ between black and red ink (red is lighter and thinner)."""
    min_speck_px: int = 8             # ink blobs smaller than this are dust, not text
    break_max_frac: float = 0.3       # headline thinner than this x its typical thickness is a break...
    break_soft_frac: float = 0.5      # ...which extends while the headline is thinner than this
    min_break_px: int = 2             # headline gaps narrower than this are not breaks
    min_piece_ink_px: int = 15        # pieces with less ink than this are specks


@dataclass
class Config:
    # ---- page preparation (C1, FR-2) ----------------------------------------------
    work_scale: float = 0.25          # paper tone is estimated on a copy this size (speed)
    paper_blur_px: int = 151          # median window (full-page px) for the paper tone; must be much wider
                                      # than a letter, or dense text pulls the estimate towards the ink colour
    scanner_rel_l: float = 0.45       # darker than this x paper lightness and touching the image edge = scanner
    black_max_rel_l: float = 0.62     # pixel is black ink if its lightness is below this x local paper lightness
    red_min_da: float = 14.0          # pixel is red ink if its Lab a* is this much above the local paper a*...
    red_min_dl: float = 8.0           # ...and it is at least this much darker (Lab L, 0-255) than the paper
    rule_min_frac: float = 0.15       # straight ink runs longer than this x page height / width are ruled lines
    rule_slant_px: int = 5            # tolerance for slanted ruled lines
    block_smooth_px: int = 41         # smoothing of the ink profiles used to find the text block
    block_col_frac: float = 0.20      # a column is in the text block if its ink is this x a typical text column
    block_row_frac: float = 0.05      # same for rows (low: gaps between lines must not split the block)
    block_gap_px: int = 60            # gaps up to this wide do not split the text block
    block_pad_px: int = 15            # margin added around the text block (matras at the edges)

    # ---- line detection (C2, FR-3) ------------------------------------------------
    line_spacing_px: int = 0          # line pitch; 0 = estimate per page (about 110 px on the samples)
    line_min_spacing_px: int = 40     # range searched when estimating the pitch
    line_max_spacing_px: int = 300
    line_min_gap_frac: float = 0.6    # headline peaks closer than this x pitch belong to one line
    line_peak_frac: float = 0.25      # weaker peaks (x a typical headline peak) are not lines
    headline_min_run_px: int = 25     # headlines are found from horizontal ink runs at least this long
    headline_window_px: int = 150     # the headline is traced in windows this wide...
    headline_search_frac: float = 0.3 # ...within this x pitch of the line's peak row
    headline_min_ink_frac: float = 0.25   # a window needs this share of inked columns at its best row
    headline_max_wave_frac: float = 0.08  # windows further than this x pitch from a smooth fit are ignored
    headline_tol_px: int = 4         # ink this close to a traced headline touches it
    main_zone_frac: float = 0.5       # fallback headline-to-main-zone-bottom distance (x pitch)
    main_zone_drop: float = 0.25      # main zone ends where row ink falls below this x letter-body ink
    line_red_share: float = 0.8       # a line is red (or black) if this share of its ink is that colour
    line_margin_px: int = 6           # margin around each line image
    line_erase_grow_px: int = 4       # other lines' ink is erased from a line image with this much extra edge

    # ---- stroke pieces (C3a, FR-4) ------------------------------------------------
    headline_above_px: int = 8        # headline thickness is measured from this far above the traced row...
    headline_below_px: int = 4        # ...to this far below (letter bodies start further down)
    piece_top_frac: float = 0.1       # a piece starts this far (x pitch) above the headline (its top edge)

    # ---- letters: join and split rules (C3b, FR-5, FR-6) -------------------------------
    min_letter_width_ratio: float = 0.45  # pieces narrower than this x the line's typical piece are not letters
    stroke_min_height_frac: float = 0.6   # a bar / danda is at least this x the piece zone tall...
    stroke_min_fill: float = 0.85         # ...with ink in this share of its rows...
    stroke_min_waist: float = 0.4         # ...and no row in its middle narrower than this x its median width
                                          # (a visarga's two dots can touch, but pinch between them)
    mark_min_px: int = 20                 # upper-mark ink touching a bar needed to call it an i-matra
    bar_head_extra_px: int = 6            # a bar's headline is at least this much wider than its stem
    bar_protect_px: int = 12              # no split cut within this distance before a joined vowel bar
    double_danda_gap_ratio: float = 0.5   # two dandas this close (x typical piece width) are one double danda
    split_width_ratio: float = 1.4        # letters wider than this x the page's typical letter may be split...
    split_gap_frac: float = 0.15          # ...where a column below the headline has at most this x the
                                          # letter's typical column ink (bodies apart, only headline joins)
    split_force_ratio: float = 2.2        # letters wider than this are split even without such a gap
    split_body_top_frac: float = 0.25     # body ink for splits is counted from this x main zone below the
                                          # headline (higher up, the headline itself fills every column)
    split_search_ratio: float = 0.3       # each cut is searched this far (x typical) around its expected place
    i_stem_edge_ratio: float = 0.45       # a short-i stem rises within this x typical of its letter's right edge...
    i_curl_cover: float = 0.5             # ...and its curl covers this share of the next letter (or of a typical one)
    digit_max_width_ratio: float = 1.5    # up to two letters this narrow between dandas are a verse number
    letter_margin_px: int = 4             # margin around each letter image

    # ---- grouping (C4, FR-7) ---------------------------------------------------------------
    normalize_size: int = 48              # letters are compared as square images this size...
    fp_blur: float = 1.0                  # ...blurred this much (px) so small shifts still match
    fp_pixels: int = 24                   # the image part of a fingerprint is this many px square
    fp_pixel_weight: float = 1.0          # weights of the image part, the stroke-direction (HOG) part
    fp_hog_weight: float = 1.0            # and the letter-size part
    fp_size_weight: float = 0.5
    group_distance: float = 0.55          # samples closer than this (0 = same, 2 = opposite) share a group
    group_rounds: int = 3                 # merge / reassign rounds after the first pass
    group_outlier_distance: float = 0.5   # a sample further than this from its group's centre is unsure;
                                          # also the limit for merging groups (90% of members within it)
    group_max_merge: int = 5000           # groups are merged only up to this many (k x k distance matrix)
    min_group_size: int = 2               # smaller groups are not groups: their samples go to "unsure"
    group_max_shown: int = 20             # samples shown per group in groups.html

    # ---- labels and the Gujarati mapping (C5b) -----------------------------------------------
    digits: str = "gujarati"              # digits in Gujarati text: "gujarati" (૧૨૩) or "western" (123)
    mapping_file: str = ""                # own copy of the Devanagari -> Gujarati exceptions; "" = built-in

    # ---- export (C5g, FR-9) ----------------------------------------------------------------------
    dataset_image: str = "original"       # dataset images: "original" crop, "normalized" (black on white)
                                          # or "fixed64" (normalized, 64 x 64)
    min_samples_warn: int = 10            # classes with fewer samples are highlighted in overview.html

    # ---- label suggestions (Phase 2: C10, C11; measured in docs/TUNING_PHASE2.md) ---------------
    ocr_langs: str = "script/Devanagari"  # Tesseract language models, joined by +
    ocr_psm: int = 7                      # Tesseract page segmentation mode: 7 = one text line
    ocr_letter_height: int = 0            # letter-body height Tesseract gets, px; 0 = the line image as it is
    align_min_overlap: float = 0.6        # an OCR akshara and a sample match from this x overlap...
    align_sure_overlap: float = 0.8       # ...if they are also each other's best match, or from this one
    align_min_matched: float = 0.5        # a line where fewer of its samples match is not used
    suggest_min_votes: int = 3            # a group needs this many read samples for a suggestion...
    suggest_min_share: float = 0.6        # ...and the winning reading this share of the weighted votes
    suggest_min_confidence: float = 80.0  # an unsure sample shows its own reading from this confidence
    bulk_accept_share: float = 0.9        # "Accept all" in the Review tab starts at this share (C12)
    books_k: int = 5                      # suggestions from other books (C13): nearest labelled groups that vote,
    books_distance: float = 0.5           # if this close (stricter than group_distance: measured in C13)
    split_distance: float = 0.25          # splitting mixed groups (C12d): the letters read as another letter leave
    split_min_samples: int = 5            # their group when their shape centre is this far from the group's main
    split_min_share: float = 0.1          # letters, and there are this many of them and this share of the group
    cut_method: str = "shapes"            # cutting letters: "shapes" (C3a, C3b) or "tesseract" (by its reading, C12c)
    tesseract_cut_min_gap: float = 0.3    # Tesseract cutting: cuts closer than this x a letter width are not made
    recut_window: float = 0.3             # fixing cuts (C12b): a cut may move this x a letter width from Tesseract's
    recut_min_width: float = 0.45         # a new sample must be at least this x a letter width wide...
    recut_min_group: int = 5              # ...and near the centre of a group with at least this many samples

    black: InkParams = field(default_factory=lambda: InkParams(
        min_speck_px=8, break_max_frac=0.3, min_break_px=2, min_piece_ink_px=15))
    red: InkParams = field(default_factory=lambda: InkParams(
        min_speck_px=5, break_max_frac=0.3, min_break_px=2, min_piece_ink_px=10))

    # ---- batch ------------------------------------------------------------------------
    workers: int = 0                  # 0 = automatic
    debug: bool = False
    save_masks: bool = False          # also write each letter's ink mask (L01_003_mask.png); the app needs them
    write_groups: bool = True         # write groups/, unsure/ and groups.html (the app keeps groups in its database)


def _apply(obj: Any, values: Dict[str, Any], where: str) -> None:
    known = {f.name: f for f in fields(obj)}
    for key, value in values.items():
        if key not in known:
            raise ValueError(f"Unknown setting in config file: {where}{key}")
        current = getattr(obj, key)
        if is_dataclass(current):
            if not isinstance(value, dict):
                raise ValueError(f"Setting {where}{key} must be an object")
            _apply(current, value, f"{where}{key}.")
        else:
            setattr(obj, key, type(current)(value))


def load_config(path: Optional[Path] = None, **overrides: Any) -> Config:
    """Defaults, then the JSON file (if given), then keyword overrides (from the CLI)."""
    cfg = Config()
    if path is not None:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            raise ValueError(f"Cannot read config file {path}: {e}") from e
        if not isinstance(data, dict):
            raise ValueError(f"Config file {path} must contain a JSON object")
        _apply(cfg, data, "")
    _apply(cfg, overrides, "")
    return cfg
