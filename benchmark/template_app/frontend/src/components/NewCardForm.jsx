import { useState } from 'react'
import { createCard } from '../api.js'

export default function NewCardForm({ columnId, onCreated }) {
  const [title, setTitle] = useState('')
  const [priority, setPriority] = useState('medium')

  async function submit(e) {
    e.preventDefault()
    if (!title.trim()) return
    await createCard(columnId, { title: title.trim(), priority })
    setTitle('')
    setPriority('medium')
    onCreated()
  }

  return (
    <form className="new-card-form" onSubmit={submit}>
      <input
        className="new-card-title"
        placeholder="Add a card…"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
      />
      <select
        className="new-card-priority"
        value={priority}
        onChange={(e) => setPriority(e.target.value)}
      >
        <option value="low">low</option>
        <option value="medium">medium</option>
        <option value="high">high</option>
      </select>
      <button type="submit" className="new-card-submit">Add</button>
    </form>
  )
}
