import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import TooltipProvider from './components/TooltipProvider'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <>
      <App />
      <TooltipProvider />
    </>
  </React.StrictMode>,
)
