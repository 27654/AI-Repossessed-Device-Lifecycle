import { useRef, useState, type FormEvent } from 'react'
import { ACCEPTED_UPLOAD_TYPES, MAX_UPLOAD_BYTES } from '../config/devices'
import { errorMessage, type Attachment } from '../lib/api'
import { dateTime, formatSize } from '../lib/format'
import { inputClass, secondaryButtonClass } from './form'
import { EmptyState } from './PageState'

// File list and upload form shared by device attachments and recovery evidence.
// Files always download through the authenticated API (`download_url`).

export function AttachmentList({ items, emptyTitle = 'No attachments yet' }: { items: Attachment[]; emptyTitle?: string }) {
  if (items.length === 0) return <EmptyState title={emptyTitle} />
  return (
    <ul className="grid gap-3 sm:grid-cols-2">
      {items.map((item) => (
        <li key={item.id} className="flex gap-3 rounded-md border border-slate-200 p-2">
          <a href={item.download_url} target="_blank" rel="noreferrer" className="shrink-0">
            {item.mime_type.startsWith('image/') ? (
              <img
                src={item.download_url}
                alt={item.description || item.original_name}
                className="h-16 w-16 rounded object-cover"
                loading="lazy"
              />
            ) : (
              <span className="flex h-16 w-16 items-center justify-center rounded bg-red-50 text-xs font-semibold text-red-700">
                PDF
              </span>
            )}
          </a>
          <div className="min-w-0 text-sm">
            <a
              href={item.download_url}
              target="_blank"
              rel="noreferrer"
              className="block truncate font-medium text-slate-900 hover:underline"
            >
              {item.original_name}
            </a>
            {item.description && <p className="truncate text-slate-600">{item.description}</p>}
            {item.recovery_reference && (
              <p className="text-xs font-medium text-amber-700">Recovery evidence · {item.recovery_reference}</p>
            )}
            {item.assessment_reference && (
              <p className="text-xs font-medium text-indigo-700">Assessment evidence · {item.assessment_reference}</p>
            )}
            {item.refurbishment_reference && (
              <p className="text-xs font-medium text-violet-700">Refurbishment evidence · {item.refurbishment_reference}</p>
            )}
            {item.disposition_reference && (
              <p className="text-xs font-medium text-teal-700">Disposition evidence · {item.disposition_reference}</p>
            )}
            <p className="text-xs text-slate-500">
              {formatSize(item.size_bytes)} · {item.uploaded_by.full_name} · {dateTime(item.created_at)}
            </p>
          </div>
        </li>
      ))}
    </ul>
  )
}

interface AttachmentUploadProps {
  title?: string
  onUpload: (file: File, description: string) => Promise<unknown>
  onUploaded: () => void
}

export function AttachmentUpload({ title = 'Upload photo or document', onUpload, onUploaded }: AttachmentUploadProps) {
  const fileInput = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [description, setDescription] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)

  function choose(selected: File | null) {
    setError(null)
    if (selected && selected.size > MAX_UPLOAD_BYTES) {
      setError('The file is larger than 5 MB.')
      selected = null
      if (fileInput.current) fileInput.current.value = ''
    }
    setFile(selected)
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!file) return
    setError(null)
    setUploading(true)
    try {
      await onUpload(file, description)
      setFile(null)
      setDescription('')
      if (fileInput.current) fileInput.current.value = ''
      onUploaded()
    } catch (err) {
      setError(errorMessage(err, 'Upload failed.'))
    } finally {
      setUploading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mt-4 space-y-3 border-t border-slate-100 pt-4">
      <p className="text-sm font-medium text-slate-700">{title}</p>
      {error && (
        <p role="alert" className="rounded-md bg-red-50 p-2 text-sm text-red-700">
          {error}
        </p>
      )}
      <input
        ref={fileInput}
        type="file"
        accept={ACCEPTED_UPLOAD_TYPES}
        onChange={(e) => choose(e.target.files?.[0] ?? null)}
        className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border-0 file:bg-slate-100 file:px-3 file:py-2 file:text-sm file:font-medium file:text-slate-700 hover:file:bg-slate-200"
      />
      <p className="text-xs text-slate-500">JPEG, PNG, WebP or PDF, up to 5 MB.</p>
      <input
        placeholder="Description (optional)"
        maxLength={255}
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        className={inputClass}
      />
      <button type="submit" disabled={!file || uploading} className={secondaryButtonClass}>
        {uploading ? 'Uploading…' : 'Upload'}
      </button>
    </form>
  )
}
