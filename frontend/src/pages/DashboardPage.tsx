import { Link } from 'react-router-dom';
import { listAgents } from '../api/agents';
import { listChatbots } from '../api/chatbots';
import { useAsync } from '../hooks/useAsync';
import { useCredits } from '../context/CreditsContext';
import { AgentCard } from '../components/AgentCard';
import { ChatbotCard } from '../components/ChatbotCard';
import { EmptyState } from '../components/EmptyState';
import { ErrorBanner } from '../components/ErrorBanner';
import { Spinner } from '../components/Spinner';
import styles from './DashboardPage.module.css';

export function DashboardPage() {
  const agents = useAsync(() => listAgents(), []);
  const chatbots = useAsync(() => listChatbots(), []);
  const { credits } = useCredits();

  return (
    <div>
      <div className={styles.hero}>
        <div className={styles.heroText}>
          <h1>Dashboard</h1>
          <p className={styles.subline}>Your agents and chatbots, all in one place.</p>
        </div>
        <div className={styles.stats}>
          <div className={styles.stat}>
            <p className={styles.statValue}>{agents.data?.length ?? '—'}</p>
            <p className={styles.statLabel}>Agents</p>
          </div>
          <div className={styles.stat}>
            <p className={styles.statValue}>{chatbots.data?.length ?? '—'}</p>
            <p className={styles.statLabel}>Chatbots</p>
          </div>
          <div className={styles.stat}>
            <p className={styles.statValue}>{credits ? credits.tokens_remaining.toLocaleString() : '—'}</p>
            <p className={styles.statLabel}>Tokens left</p>
          </div>
        </div>
      </div>

      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2>My agents</h2>
          <Link className="btn btn-primary" to="/agents/new" data-tour="create-agent-btn">
            Create new
          </Link>
        </div>
        {agents.loading && <Spinner />}
        {agents.error && <ErrorBanner message={agents.error} />}
        {!agents.loading && !agents.error && agents.data?.length === 0 && (
          <EmptyState
            title="No agents yet"
            description="Create a standalone agent to start chatting and uploading documents."
          />
        )}
        {!agents.loading && !agents.error && agents.data && agents.data.length > 0 && (
          <div className={styles.grid}>
            {agents.data.map((agent) => (
              <AgentCard key={agent.id} agent={agent} onRenamed={agents.reload} />
            ))}
          </div>
        )}
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2>My chatbots</h2>
          <Link className="btn btn-primary" to="/chatbots/new" data-tour="create-chatbot-btn">
            Create new
          </Link>
        </div>
        {chatbots.loading && <Spinner />}
        {chatbots.error && <ErrorBanner message={chatbots.error} />}
        {!chatbots.loading && !chatbots.error && chatbots.data?.length === 0 && (
          <EmptyState
            title="No chatbots yet"
            description="Create a chatbot to orchestrate multiple agents behind one conversation."
          />
        )}
        {!chatbots.loading && !chatbots.error && chatbots.data && chatbots.data.length > 0 && (
          <div className={styles.grid}>
            {chatbots.data.map((chatbot) => (
              <ChatbotCard key={chatbot.id} chatbot={chatbot} onRenamed={chatbots.reload} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
