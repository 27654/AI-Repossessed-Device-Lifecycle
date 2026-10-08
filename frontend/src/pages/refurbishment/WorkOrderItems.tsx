import { useState, type FormEvent } from 'react'
import { inputClass, secondaryButtonClass } from '../../components/form'
import { errorMessage, fieldErrors, refurbishmentApi, type ItemInput, type RefurbishmentItem, type WorkOrder } from '../../lib/api'
import { rwf } from '../../lib/format'

const EMPTY: ItemInput = { item_name: '', part_number: '', quantity: 1, unit_cost_rwf: 0, supplier: '', notes: '' }

function ItemForm({
  initial,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initial: ItemInput
  submitLabel: string
  onSubmit: (input: ItemInput) => Promise<unknown>
  onCancel?: () => void
}) {
  const [values, setValues] = useState(initial)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const set = (field: keyof ItemInput) => (value: string) =>
    setValues((v) => ({ ...v, [field]: field === 'quantity' || field === 'unit_cost_rwf' ? Number(value) : value }))

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setErrors({})
    setError(null)
    setSaving(true)
    try {
      await onSubmit(values)
      setValues(EMPTY)
    } catch (err) {
      const fields = fieldErrors(err)
      setErrors(fields)
      setError(Object.keys(fields).length ? null : errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  const fieldError = (field: string) =>
    errors[field] && <span className="mt-1 block text-xs text-red-600">{errors[field]}</span>

  return (
    <form onSubmit={handleSubmit} className="space-y-2 rounded-md border border-slate-200 p-3" noValidate>
      {error && (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      )}
      <div className="grid gap-2 sm:grid-cols-4">
        <label className="block text-sm sm:col-span-2">
          <span className="text-slate-600">Part / material *</span>
          <input value={values.item_name} maxLength={120} onChange={(e) => set('item_name')(e.target.value)} className={inputClass} />
          {fieldError('item_name')}
        </label>
        <label className="block text-sm">
          <span className="text-slate-600">Quantity *</span>
          <input type="number" min={1} step={1} value={values.quantity} onChange={(e) => set('quantity')(e.target.value)} className={inputClass} />
          {fieldError('quantity')}
        </label>
        <label className="block text-sm">
          <span className="text-slate-600">Unit cost (RWF) *</span>
          <input type="number" min={0} step={1} value={values.unit_cost_rwf} onChange={(e) => set('unit_cost_rwf')(e.target.value)} className={inputClass} />
          {fieldError('unit_cost_rwf')}
        </label>
        <label className="block text-sm">
          <span className="text-slate-600">Part number</span>
          <input value={values.part_number} maxLength={60} onChange={(e) => set('part_number')(e.target.value)} className={inputClass} />
        </label>
        <label className="block text-sm">
          <span className="text-slate-600">Supplier</span>
          <input value={values.supplier} maxLength={120} onChange={(e) => set('supplier')(e.target.value)} className={inputClass} />
        </label>
        <label className="block text-sm sm:col-span-2">
          <span className="text-slate-600">Notes</span>
          <input value={values.notes} onChange={(e) => set('notes')(e.target.value)} className={inputClass} />
        </label>
      </div>
      <p className="text-xs text-slate-500">
        Line total: {rwf((values.quantity || 0) * (values.unit_cost_rwf || 0))} (calculated by the server)
      </p>
      <div className="flex gap-2">
        <button type="submit" disabled={saving} className={secondaryButtonClass}>
          {saving ? 'Saving…' : submitLabel}
        </button>
        {onCancel && (
          <button type="button" onClick={onCancel} className={secondaryButtonClass}>
            Cancel
          </button>
        )}
      </div>
    </form>
  )
}

const toInput = (item: RefurbishmentItem): ItemInput => ({
  item_name: item.item_name,
  part_number: item.part_number,
  quantity: item.quantity,
  unit_cost_rwf: item.unit_cost_rwf,
  supplier: item.supplier,
  notes: item.notes,
})

interface WorkOrderItemsProps {
  workOrder: WorkOrder
  canManage: boolean
  onChanged: () => void
}

// Parts and materials, with totals. Editable only while the work order is active.
export default function WorkOrderItems({ workOrder, canManage, onChanged }: WorkOrderItemsProps) {
  const active = workOrder.status === 'OPEN' || workOrder.status === 'IN_PROGRESS'
  const [editing, setEditing] = useState<number | null>(null)
  const [adding, setAdding] = useState(false)

  return (
    <div className="space-y-2">
      <p className="text-sm font-medium text-slate-700">Parts and materials</p>
      {workOrder.items.length === 0 ? (
        <p className="text-sm text-slate-500">No parts recorded.</p>
      ) : (
        <div className="overflow-x-auto rounded-md border border-slate-200">
          <table className="w-full min-w-[560px] text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2 font-medium">Item</th>
                <th className="px-3 py-2 text-right font-medium">Qty</th>
                <th className="px-3 py-2 text-right font-medium">Unit</th>
                <th className="px-3 py-2 text-right font-medium">Total</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {workOrder.items.map((item) =>
                editing === item.id ? (
                  <tr key={item.id}>
                    <td colSpan={5} className="p-2">
                      <ItemForm
                        initial={toInput(item)}
                        submitLabel="Save part"
                        onCancel={() => setEditing(null)}
                        onSubmit={async (input) => {
                          await refurbishmentApi.updateItem(item.id, input)
                          setEditing(null)
                          onChanged()
                        }}
                      />
                    </td>
                  </tr>
                ) : (
                  <tr key={item.id}>
                    <td className="px-3 py-2">
                      <span className="font-medium text-slate-900">{item.item_name}</span>
                      <div className="text-xs text-slate-500">
                        {[item.part_number, item.supplier, item.notes].filter(Boolean).join(' · ')}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-right">{item.quantity}</td>
                    <td className="px-3 py-2 text-right">{rwf(item.unit_cost_rwf)}</td>
                    <td className="px-3 py-2 text-right font-medium">{rwf(item.total_cost_rwf)}</td>
                    <td className="px-3 py-2 text-right">
                      {canManage && active && (
                        <button type="button" onClick={() => setEditing(item.id)} className="text-xs text-slate-600 underline">
                          Edit
                        </button>
                      )}
                    </td>
                  </tr>
                ),
              )}
              <tr className="bg-slate-50">
                <td colSpan={3} className="px-3 py-2 text-right font-medium">
                  Parts total
                </td>
                <td className="px-3 py-2 text-right font-semibold">{rwf(workOrder.parts_cost_rwf)}</td>
                <td />
              </tr>
            </tbody>
          </table>
        </div>
      )}
      {canManage && active &&
        (adding ? (
          <ItemForm
            initial={EMPTY}
            submitLabel="Add part"
            onCancel={() => setAdding(false)}
            onSubmit={async (input) => {
              await refurbishmentApi.addItem(workOrder.id, input)
              setAdding(false)
              onChanged()
            }}
          />
        ) : (
          <button type="button" onClick={() => setAdding(true)} className={secondaryButtonClass}>
            Add part / material
          </button>
        ))}
    </div>
  )
}
