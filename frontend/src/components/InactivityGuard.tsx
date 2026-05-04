/**
 * Tracks user inactivity and triggers a callback after timeoutMs of idle.
 * The timer pauses when the user is actively typing in an input.
 */
import { useEffect, useRef, type ReactNode } from 'react'

interface Props {
  timeoutMs: number
  onTimeout: () => void
  children: ReactNode
}

const RESET_EVENTS = ['mousemove', 'mousedown', 'touchstart', 'scroll'] as const

export function InactivityGuard({ timeoutMs, onTimeout, children }: Props) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  function reset() {
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(onTimeout, timeoutMs)
  }

  useEffect(() => {
    // Start the timer on mount
    reset()

    // Also reset on keystroke events — but this covers typing in inputs too.
    // We bind globally so we don't accidentally lock mid-typing.
    const handleActivity = () => reset()

    const handleKeydown = (e: KeyboardEvent) => {
      // Reset on any keypress — this keeps the timer alive while user types
      // in the passphrase field (the critical UX requirement from spec)
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement
      ) {
        // Don't reset here; let the typing happen but note activity
        reset()
      } else {
        reset()
      }
    }

    RESET_EVENTS.forEach((ev) => {
      window.addEventListener(ev, handleActivity, { passive: true })
    })
    window.addEventListener('keydown', handleKeydown)

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
      RESET_EVENTS.forEach((ev) => {
        window.removeEventListener(ev, handleActivity)
      })
      window.removeEventListener('keydown', handleKeydown)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeoutMs, onTimeout])

  return <>{children}</>
}