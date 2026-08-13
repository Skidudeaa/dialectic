import type { HomeActivityMovement, RoomDestination } from '../../types'
import './HouseMovement.css'

const KIND_LABELS: Record<HomeActivityMovement['kind'], string> = {
  reading_filed: 'Reading filed',
  research_completed: 'Research completed',
  claim_warning: 'Claim warning',
  wire_interruption: 'The wire interrupted',
  prediction_review: 'Prediction review',
  commitment_due: 'Commitment due',
  echo_created: 'Echo',
  thesis_lifecycle: 'Thesis',
}

interface HouseMovementProps {
  movement: HomeActivityMovement[]
  onNavigate: (destination: RoomDestination) => Promise<boolean> | void
}

/**
 * What moved in the house, as movement — not as a second copy of the object.
 *
 * WHY it navigates by room/branch rather than by the `destination` string:
 * the navigation transaction owns URL construction. Handing it a pre-built URL
 * would make this component a second destination writer, which is exactly the
 * pattern useRoomNavigation exists to prevent. The server's `destination` is
 * carried for provenance and asserted against in tests.
 */
export function HouseMovement({ movement, onNavigate }: HouseMovementProps) {
  if (movement.length === 0) return null

  return (
    <section className="house-movement" aria-label="What moved">
      <h2>What moved</h2>
      <div className="house-movement-list">
        {movement.map((item) => (
          <button
            key={`${item.kind}:${item.object_id ?? item.occurred_at}`}
            type="button"
            className={`house-movement-item${item.requires_judgment ? ' needs-judgment' : ''}`}
            onClick={() => {
              void onNavigate({
                roomId: item.room_id,
                threadId: item.thread_id,
              })
            }}
          >
            <span className="house-movement-kind">{KIND_LABELS[item.kind]}</span>
            <span className="house-movement-title">{item.title}</span>
          </button>
        ))}
      </div>
    </section>
  )
}
