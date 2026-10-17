// Keep the canvas allocation and resize subscription for its mounted lifetime.
// A new tracking frame only clears and paints the existing backing buffer.
export function createReplayCanvas(canvas, draw, {
  Observer = ResizeObserver,
  readDensity = () => window.devicePixelRatio || 1,
} = {}) {
  const context = canvas.getContext("2d");
  let active = true;
  const paint = () => {
    if (!active) return;
    const width = canvas.clientWidth, height = canvas.clientHeight;
    if (!width || !height) return;
    const density = readDensity();
    const pixelWidth = Math.round(width * density), pixelHeight = Math.round(height * density);
    if (canvas.width !== pixelWidth) canvas.width = pixelWidth;
    if (canvas.height !== pixelHeight) canvas.height = pixelHeight;
    context.setTransform(density, 0, 0, density, 0, 0);
    context.clearRect(0, 0, width, height);
    draw(context, width, height);
  };
  const observer = new Observer(paint);
  observer.observe(canvas);
  return {
    paint,
    close() {
      active = false;
      observer.disconnect();
      context.clearRect(0, 0, canvas.width, canvas.height);
    },
  };
}
