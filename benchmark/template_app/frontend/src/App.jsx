import { useCallback, useEffect, useState } from 'react'
import { getBoard, getBoards } from './api.js'
import Header from './components/Header.jsx'
import Board from './components/Board.jsx'

export default function App() {
  const [board, setBoard] = useState(null)
  const [error, setError] = useState(null)

  const refresh = useCallback(async () => {
    try {
      const boards = await getBoards()
      if (boards.length === 0) {
        setError('No boards yet.')
        return
      }
      setBoard(await getBoard(boards[0].id))
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  if (error) return <p className="error">{error}</p>
  if (!board) return <p className="loading">Loading…</p>

  return (
    <div className="app">
      <Header boardName={board.name} />
      <Board board={board} onChange={refresh} />
    </div>
  )
}
