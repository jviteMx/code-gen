import Column from './Column.jsx'

export default function Board({ board, onChange }) {
  return (
    <main className="board">
      {board.columns.map((column) => (
        <Column key={column.id} column={column} onChange={onChange} />
      ))}
    </main>
  )
}
