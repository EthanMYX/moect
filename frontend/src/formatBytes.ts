export function formatBytes(value: number) {
  if (!Number.isFinite(value) || value < 0) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let unit = 0,
    size = value;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit++;
  }
  return (unit ? size.toFixed(1) : size.toFixed(0)) + " " + units[unit];
}
