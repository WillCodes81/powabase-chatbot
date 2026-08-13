import { Link } from 'react-router-dom';
import type { ChatbotSummary } from '../api/types';
import styles from './Card.module.css';

export function ChatbotCard({ chatbot }: { chatbot: ChatbotSummary }) {
  return (
    <Link to={`/chatbots/${chatbot.id}`} className={styles.card}>
      <p className={styles.name}>
        <span className={styles.dot} />
        {chatbot.name}
      </p>
      <p className={styles.meta}>{chatbot.orchestrator_id}</p>
    </Link>
  );
}
