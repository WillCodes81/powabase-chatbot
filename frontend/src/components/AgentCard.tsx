import { Link } from 'react-router-dom';
import type { AgentSummary } from '../api/types';
import styles from './Card.module.css';

export function AgentCard({ agent }: { agent: AgentSummary }) {
  return (
    <Link to={`/agents/${agent.agent_id}`} className={styles.card}>
      <p className={styles.name}>
        <span className={styles.dot} />
        {agent.name}
      </p>
      <p className={styles.meta}>{agent.agent_id}</p>
    </Link>
  );
}
