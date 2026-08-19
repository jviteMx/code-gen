export default function Card({ card }) {
  return (
    <article className="card" data-card-id={card.id}>
      <div className="card-title">{card.title}</div>
      <div className="card-meta">
        <span className={`priority-badge priority-${card.priority}`}>{card.priority}</span>
        {card.due_date && <span className="due-date">{card.due_date}</span>}
      </div>
    </article>
  )
}
