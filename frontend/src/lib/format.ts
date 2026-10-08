// Display formatting shared by pages.

export const dateTime = (value: string) =>
  new Date(value).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })

// A YYYY-MM-DD date, shown without shifting it through UTC.
export const date = (value: string) =>
  new Date(`${value}T00:00:00`).toLocaleDateString(undefined, { dateStyle: 'medium' })

export function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// ISO timestamp -> value for <input type="datetime-local"> in the browser's time zone.
export function toLocalInput(value: string | Date) {
  const d = typeof value === 'string' ? new Date(value) : value
  const local = new Date(d.getTime() - d.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

// <input type="datetime-local"> value -> ISO timestamp with time zone for the API.
export const fromLocalInput = (value: string) => new Date(value).toISOString()
