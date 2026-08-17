import { Link } from 'react-router-dom';
import type { AgentSummary } from '../api/types';
import { updateAgentName } from '../api/agents';
import { EditableName } from './EditableName';
import styles from './Card.module.css';

export function AgentCard({ agent, onRenamed }: { agent: AgentSummary; onRenamed: () => void }) {
  return (
    <Link to={`/agents/${agent.agent_id}`} className={styles.card}>
      <p className={styles.name}>
        <span className={styles.dot} />
        <EditableName
          value={agent.name}
          onSave={async (newName) => {
            await updateAgentName(agent.agent_id, newName);
            onRenamed();
          }}
        />
      </p>
      <p className={styles.meta}>{agent.agent_id}</p>
    </Link>
  );
}
