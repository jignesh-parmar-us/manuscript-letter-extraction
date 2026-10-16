"""The letter reader (C14): a small network in NumPy that learns letters from their shape features.

One hidden layer (`hidden` units, ReLU) and a softmax over the labels, trained with Adam on mini-batches,
L2 weight decay and dropout. Features are standardised with the training set's means and spreads.
Training stops when the loss on the validation letters (letters of pages kept out of training) has not
improved for `patience` epochs, and the best weights are kept. With `hidden=0` it is a plain softmax
regression (a linear reader), used for comparison.

PyTorch and ONNX Runtime do not install on the development computer (Intel Mac, Python 3.14; plan
Section 1), so the network is written out here; for a few thousand letters it trains in a minute.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np


@dataclass
class TrainResult:
    epochs: int
    best_epoch: int
    val_loss: float
    history: List[Dict] = field(default_factory=list)


def adam_step(prm: np.ndarray, gr: np.ndarray, m: np.ndarray, v: np.ndarray, buf, step: int, lr: float) -> None:
    """One Adam step in place (S4c): m = 0.9 m + 0.1 g, v = 0.999 v + 0.001 g g, p -= lr m^ / (sqrt(v^) + 1e-8), with
    m^, v^ the bias-corrected moments; the same operations in the same order as written out, without new arrays.
    `buf`: two scratch arrays of the parameter's shape."""
    a, b = buf
    m *= 0.9
    np.multiply(gr, 0.1, out=a)
    m += a
    v *= 0.999
    np.multiply(gr, 0.001, out=a)
    a *= gr
    v += a
    np.divide(m, 1 - 0.9 ** step, out=a)
    a *= lr
    np.divide(v, 1 - 0.999 ** step, out=b)
    np.sqrt(b, out=b)
    b += 1e-8
    a /= b
    prm -= a


class LetterReader:
    def __init__(self, classes: Sequence[str], dim: int, hidden: int = 384, seed: int = 0):
        self.classes = list(classes)
        self.dim, self.hidden = dim, hidden
        rng = np.random.default_rng(seed)
        self.mean = np.zeros(dim, np.float32)
        self.std = np.ones(dim, np.float32)
        n_out = len(self.classes)
        if hidden:
            self.W1 = (rng.standard_normal((dim, hidden)) * np.sqrt(2.0 / dim)).astype(np.float32)
            self.b1 = np.zeros(hidden, np.float32)
            self.W2 = (rng.standard_normal((hidden, n_out)) * np.sqrt(1.0 / hidden)).astype(np.float32)
        else:
            self.W1 = self.b1 = None
            self.W2 = (rng.standard_normal((dim, n_out)) * 0.01).astype(np.float32)
        self.b2 = np.zeros(n_out, np.float32)

    # ---- using it ---------------------------------------------------------------------------------
    def _params(self) -> List[np.ndarray]:
        return [p for p in (self.W1, self.b1, self.W2, self.b2) if p is not None]

    def _forward(self, X: np.ndarray, drop: float = 0.0, rng=None):
        Z = (X - self.mean) / self.std
        if self.hidden:
            H = np.maximum(Z @ self.W1 + self.b1, 0.0)
            mask = None
            if drop:
                mask = (rng.random(H.shape) >= drop).astype(np.float32) / (1 - drop)
                H = H * mask
            logits = H @ self.W2 + self.b2
            return Z, H, mask, logits
        return Z, None, None, Z @ self.W2 + self.b2

    def probabilities(self, X: np.ndarray) -> np.ndarray:
        """Class probabilities, one row per letter."""
        out = []
        for i in range(0, len(X), 2048):
            logits = self._forward(X[i:i + 2048].astype(np.float32))[3]
            logits -= logits.max(axis=1, keepdims=True)
            e = np.exp(logits)
            out.append(e / e.sum(axis=1, keepdims=True))
        return np.concatenate(out) if out else np.zeros((0, len(self.classes)), np.float32)

    # ---- training ----------------------------------------------------------------------------------
    def train(self, X: np.ndarray, y: np.ndarray, Xv: Optional[np.ndarray] = None, yv: Optional[np.ndarray] = None,
              epochs: int = 60, batch: int = 128, lr: float = 2e-3, decay: float = 1e-4, drop: float = 0.2,
              patience: int = 6, weights: Optional[np.ndarray] = None, seed: int = 0,
              progress: Optional[Callable[[int, int, float], None]] = None,
              cancel: Optional[Callable[[], bool]] = None) -> TrainResult:
        """Train on (X, y): y are class indices. (Xv, yv) decide when to stop; without them it trains
        `epochs` epochs. `weights` (per letter) let rare labels count more."""
        rng = np.random.default_rng(seed)
        X = X.astype(np.float32)
        self.mean = X.mean(axis=0)
        self.std = X.std(axis=0) + 1e-4
        params = self._params()
        m = [np.zeros_like(p) for p in params]
        v = [np.zeros_like(p) for p in params]
        buf = [(np.empty_like(p), np.empty_like(p)) for p in params]   # Adam's steps in place (S4c)
        w_all = np.ones(len(X), np.float32) if weights is None else weights.astype(np.float32)
        best, best_state, best_epoch, waited, step = np.inf, None, 0, 0, 0
        history = []
        for epoch in range(1, epochs + 1):
            if cancel and cancel():
                break
            order = rng.permutation(len(X))
            total = 0.0
            for i in range(0, len(X), batch):
                idx = order[i:i + batch]
                xb, yb, wb = X[idx], y[idx], w_all[idx]
                Z, H, mask, logits = self._forward(xb, drop, rng)
                logits -= logits.max(axis=1, keepdims=True)
                p = np.exp(logits)
                p /= p.sum(axis=1, keepdims=True)
                total += float(-(wb * np.log(p[np.arange(len(yb)), yb] + 1e-9)).sum())
                g = p
                g[np.arange(len(yb)), yb] -= 1.0
                g *= (wb / wb.sum())[:, None]
                if self.hidden:
                    gW2 = H.T @ g
                    gb2 = g.sum(axis=0)
                    gH = (g @ self.W2.T) * (H > 0)
                    if mask is not None:
                        gH *= mask
                    gW1 = Z.T @ gH
                    gb1 = gH.sum(axis=0)
                    grads = [gW1 + decay * self.W1, gb1, gW2 + decay * self.W2, gb2]
                else:
                    grads = [Z.T @ g + decay * self.W2, g.sum(axis=0)]
                step += 1
                for k, (prm, gr) in enumerate(zip(params, grads)):
                    adam_step(prm, gr, m[k], v[k], buf[k], step, lr)
            val = self.loss(Xv, yv) if Xv is not None and len(Xv) else total / len(X)
            history.append({"epoch": epoch, "train_loss": round(total / len(X), 4), "val_loss": round(val, 4)})
            if progress:
                progress(epoch, epochs, val)
            if val < best - 1e-4:
                best, best_epoch, waited = val, epoch, 0
                best_state = [p.copy() for p in params]
            else:
                waited += 1
                if Xv is not None and len(Xv) and waited >= patience:
                    break
        if best_state is not None:
            for prm, saved in zip(params, best_state):
                prm[...] = saved
        return TrainResult(len(history), best_epoch, float(best), history)

    def loss(self, X: np.ndarray, y: np.ndarray) -> float:
        p = self.probabilities(X)
        return float(-np.log(p[np.arange(len(y)), y] + 1e-9).mean())

    # ---- saving ---------------------------------------------------------------------------------------
    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        arrays = {"mean": self.mean, "std": self.std, "W2": self.W2, "b2": self.b2}
        if self.hidden:
            arrays.update(W1=self.W1, b1=self.b1)
        np.savez_compressed(path, **arrays)
        path.with_suffix(".json").write_text(json.dumps({"classes": self.classes, "dim": self.dim,
                                                         "hidden": self.hidden}, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "LetterReader":
        path = Path(path)
        meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        r = cls(meta["classes"], meta["dim"], meta["hidden"])
        with np.load(path) as data:
            r.mean, r.std, r.W2, r.b2 = data["mean"], data["std"], data["W2"], data["b2"]
            if r.hidden:
                r.W1, r.b1 = data["W1"], data["b1"]
        return r
