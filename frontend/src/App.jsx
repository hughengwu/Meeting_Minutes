import { BrowserRouter, Route, Routes } from 'react-router-dom'
import Home from './pages/Home'
import Meeting from './pages/Meeting'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/meeting/:id" element={<Meeting />} />
      </Routes>
    </BrowserRouter>
  )
}
