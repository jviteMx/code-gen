export default function Header({ boardName }) {
  return (
    <header className="header">
      <h1 className="app-title">Kanbanlite</h1>
      <span className="board-name">{boardName}</span>
    </header>
  )
}
