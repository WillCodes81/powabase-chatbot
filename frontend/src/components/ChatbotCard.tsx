import { Link } from 'react-router-dom';
import type { ChatbotSummary } from '../api/types';
import { updateChatbotName } from '../api/chatbots';
import { EditableName } from './EditableName';
import styles from './Card.module.css';

export function ChatbotCard({ chatbot, onRenamed }: { chatbot: ChatbotSummary; onRenamed: () => void }) {
  return (
    <div className={styles.card}>
      <Link
        to={`/chatbots/${chatbot.id}`}
        className={styles.cardLink}
        aria-label={`View chatbot ${chatbot.name}`}
      />
      <div className={styles.cardContent}>
        <p className={styles.name}>
          <span className={styles.dot} />
          <EditableName
            value={chatbot.name}
            onSave={async (newName) => {
              await updateChatbotName(chatbot.id, newName);
              onRenamed();
            }}
          />
        </p>
        <p className={styles.meta}>{chatbot.orchestrator_id}</p>
        <span className={styles.badge}>Chatbot</span>
      </div>
    </div>
  );
}
