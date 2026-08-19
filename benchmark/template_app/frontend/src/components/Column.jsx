import Card from './Card.jsx'
import NewCardForm from './NewCardForm.jsx'

export default function Column({ column, onChange }) {
  return (
    <section className="column" data-column-id={column.id}>
      <div className="column-header">
        <h2 className="column-title">{column.name}</h2>
      </div>
      <div className="card-list">
        {column.cards.map((card) => (
          <Card key={card.id} card={card} onChange={onChange} />
        ))}
      </div>
      <NewCardForm columnId={column.id} onCreated={onChange} />
    </section>
  )
}
