import { useCallback, useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';

/**
 * SlipScanner — walks the camera down a till slip of any length.
 *
 * 1. Live camera preview with a capture frame.
 * 2. Each tap captures the framed section. From the second shot on, the
 *    bottom strip of the previous capture is ghosted at the top of the
 *    frame, so the user slides the paper until the faded strip lines up
 *    with the same text on the slip — that overlap is what stitching uses.
 * 3. "Done" stitches the sections into one tall image (grayscale
 *    template-matching finds the real overlap per pair) and hands the
 *    result back as a File for the normal OCR pipeline.
 */

interface Capture {
  canvas: HTMLCanvasElement;
  thumb: string;
}

type Phase = 'intro' | 'camera' | 'stitching' | 'review';

const MAX_WIDTH = 1000; // stitched output width in px
const DS_WIDTH = 120; // template-match working width

export default function SlipScanner({
  onClose,
  onScanned,
}: {
  onClose: () => void;
  onScanned: (file: File) => void;
}) {
  const [phase, setPhase] = useState<Phase>('intro');
  const [error, setError] = useState<string | null>(null);
  const [captures, setCaptures] = useState<Capture[]>([]);
  const [flash, setFlash] = useState(false);

  const videoRef = useRef<HTMLVideoElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const guideRef = useRef<HTMLDivElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const capturesRef = useRef<Capture[]>([]);

  const stopCamera = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  useEffect(() => stopCamera, [stopCamera]);

  async function openCamera() {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment', width: { ideal: 1920 }, height: { ideal: 1080 } },
        audio: false,
      });
      streamRef.current = stream;
      setPhase('camera');
      // Wait for the video element to mount, then attach the stream.
      requestAnimationFrame(() => {
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          void videoRef.current.play();
        }
      });
    } catch {
      setError('Camera unavailable — check permissions, or use "Upload an image" instead.');
    }
  }

  /** Crop the current video frame to the guide box, in full sensor resolution. */
  function grabFrame(): HTMLCanvasElement | null {
    const video = videoRef.current;
    const stage = stageRef.current;
    const guide = guideRef.current;
    if (!video || !stage || !guide || !video.videoWidth) return null;

    // Map container pixels -> video pixels (video uses object-fit: cover).
    const rect = stage.getBoundingClientRect();
    const g = guide.getBoundingClientRect();
    const scale = Math.max(rect.width / video.videoWidth, rect.height / video.videoHeight);
    const offX = (video.videoWidth - rect.width / scale) / 2;
    const offY = (video.videoHeight - rect.height / scale) / 2;

    const sx = offX + (g.left - rect.left) / scale;
    const sy = offY + (g.top - rect.top) / scale;
    const sw = g.width / scale;
    const sh = g.height / scale;

    const w = Math.min(MAX_WIDTH, Math.round(sw));
    const canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = Math.round((sh * w) / sw);
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    ctx.drawImage(video, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
    return canvas;
  }

  function capture() {
    const canvas = grabFrame();
    if (!canvas) return;
    setFlash(true);
    setTimeout(() => setFlash(false), 180);
    const next = [...capturesRef.current, { canvas, thumb: canvas.toDataURL('image/jpeg', 0.6) }];
    capturesRef.current = next;
    setCaptures(next);
  }

  async function finish() {
    const shots = capturesRef.current;
    if (shots.length === 0) return;
    setPhase('stitching');
    stopCamera();
    // Yield a frame so the "Stitching…" state paints before the work.
    await new Promise((r) => setTimeout(r, 30));
    try {
      const stitched = shots.length === 1 ? shots[0].canvas : await stitchCanvases(shots.map((c) => c.canvas));
      const blob = await new Promise<Blob | null>((resolve) => stitched.toBlob(resolve, 'image/jpeg', 0.9));
      if (!blob) throw new Error('encode failed');
      onScanned(new File([blob], `slip-scan-${Date.now()}.jpg`, { type: 'image/jpeg' }));
    } catch {
      setError('Could not stitch those sections. Try again with more overlap.');
      setPhase('camera');
    }
  }

  function removeLast() {
    const next = capturesRef.current.slice(0, -1);
    capturesRef.current = next;
    setCaptures(next);
  }

  const last = captures.length > 0 ? captures[captures.length - 1] : null;

  return (
    <motion.div
      className="scanner-backdrop"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      role="dialog"
      aria-modal="true"
      aria-label="Slip scanner"
    >
      <div className="scanner-modal">
        <div className="scanner-head">
          <strong>Slip scanner</strong>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close scanner">
            ✕
          </button>
        </div>

        {error && <p className="form-error scanner-error">{error}</p>}

        {phase === 'intro' && (
          <div className="scanner-intro">
            <p>
              Hold your phone over the <strong>top</strong> of the slip. Capture a section, then slide the paper
              up so the faded strip lines up with the same text — keep going until you've covered the whole
              slip, however long it is.
            </p>
            <button type="button" onClick={openCamera}>
              Open camera
            </button>
          </div>
        )}

        {(phase === 'camera' || phase === 'stitching') && (
          <div className="scanner-stage" ref={stageRef}>
            <video ref={videoRef} playsInline muted />
            <div className={phase === 'stitching' ? 'scanner-guide stitching' : 'scanner-guide'} ref={guideRef}>
              {last && (
                <img
                  className="scanner-ghost"
                  src={last.thumb}
                  alt=""
                  aria-hidden="true"
                  style={{ opacity: phase === 'stitching' ? 0 : undefined }}
                />
              )}
              {phase === 'stitching' && <span className="scanner-stitching">Stitching…</span>}
            </div>
            {flash && <div className="scanner-flash" />}
          </div>
        )}

        {phase === 'camera' && (
          <div className="scanner-actions">
            <button type="button" className="button-ghost" onClick={removeLast} disabled={captures.length === 0}>
              Undo
            </button>
            <button type="button" onClick={capture}>
              {captures.length === 0 ? 'Capture top section' : `Capture section ${captures.length + 1}`}
            </button>
            <button
              type="button"
              className="button-secondary"
              onClick={finish}
              disabled={captures.length === 0}
            >
              Done{captures.length > 0 ? ` (${captures.length})` : ''}
            </button>
          </div>
        )}

        {phase === 'stitching' && (
          <div className="scanner-actions">
            <span className="scanner-count">Joining {captures.length} sections…</span>
          </div>
        )}

        {captures.length > 0 && phase !== 'stitching' && (
          <div className="scanner-strip" aria-label={`Sections captured: ${captures.length}`}>
            {captures.map((c, i) => (
              <img key={i} src={c.thumb} alt={`Section ${i + 1}`} />
            ))}
          </div>
        )}
      </div>
    </motion.div>
  );
}

/* ---------------------------------------------------------------- */
/* Stitching: find the real overlap between consecutive sections     */
/* by grayscale template matching, then paste them into one canvas.  */
/* ---------------------------------------------------------------- */

function grayData(canvas: HTMLCanvasElement, width: number): { data: Float32Array; h: number } {
  const h = Math.round((canvas.height * width) / canvas.width);
  const c = document.createElement('canvas');
  c.width = width;
  c.height = h;
  const ctx = c.getContext('2d');
  if (!ctx) return { data: new Float32Array(0), h: 0 };
  ctx.drawImage(canvas, 0, 0, width, h);
  const { data: px } = ctx.getImageData(0, 0, width, h);
  const gray = new Float32Array(width * h);
  let sum = 0;
  for (let i = 0; i < gray.length; i++) {
    const r = px[i * 4];
    const g = px[i * 4 + 1];
    const b = px[i * 4 + 2];
    gray[i] = 0.299 * r + 0.587 * g + 0.114 * b;
    sum += gray[i];
  }
  // Mean-centre so exposure drift between sections doesn't skew matching.
  const mean = sum / gray.length;
  for (let i = 0; i < gray.length; i++) gray[i] -= mean;
  return { data: gray, h };
}

function findOverlapPx(prev: HTMLCanvasElement, next: HTMLCanvasElement): number {
  const a = grayData(prev, DS_WIDTH);
  const b = grayData(next, DS_WIDTH);
  const scale = prev.height / a.h;
  const tH = Math.min(50, Math.floor(a.h / 4), Math.floor(b.h / 4)); // template rows
  if (tH < 8) return 0;
  const maxOv = Math.min(a.h, b.h) - tH - 2;
  if (maxOv < 4) return 0;

  // Template = top strip of `next`; slide it over the bottom of `prev`.
  const rowLen = DS_WIDTH;
  let bestOv = 0;
  let bestCost = Infinity;
  for (let ov = 4; ov <= maxOv; ov++) {
    let cost = 0;
    const aStart = (a.h - ov) * rowLen;
    for (let row = 0; row < tH; row++) {
      const aOff = aStart + row * rowLen;
      const bOff = row * rowLen;
      for (let x = 0; x < rowLen; x++) {
        const d = a.data[aOff + x] - b.data[bOff + x];
        cost += d < 0 ? -d : d;
      }
    }
    if (cost < bestCost) {
      bestCost = cost;
      bestOv = ov;
    }
  }
  return Math.round(bestOv * scale);
}

async function stitchCanvases(canvases: HTMLCanvasElement[]): Promise<HTMLCanvasElement> {
  // Normalise every section to the same working width.
  const W = Math.min(MAX_WIDTH, ...canvases.map((c) => c.width));
  const norm = canvases.map((c) => {
    if (c.width === W) return c;
    const scaled = document.createElement('canvas');
    scaled.width = W;
    scaled.height = Math.round((c.height * W) / c.width);
    scaled.getContext('2d')!.drawImage(c, 0, 0, scaled.width, scaled.height);
    return scaled;
  });

  const overlaps = norm.slice(1).map((c, i) => findOverlapPx(norm[i], c));

  const out = document.createElement('canvas');
  out.width = W;
  out.height = norm.reduce((total, c, i) => total + c.height - (i > 0 ? overlaps[i - 1] : 0), 0);
  const ctx = out.getContext('2d')!;
  let y = 0;
  norm.forEach((c, i) => {
    const ov = i > 0 ? overlaps[i - 1] : 0;
    ctx.drawImage(c, 0, y - ov);
    y += c.height - ov;
  });
  return out;
}
