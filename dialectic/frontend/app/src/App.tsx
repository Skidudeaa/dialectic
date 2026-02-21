import './styles/global.css'
import { useAppStore } from './stores/appStore.ts'
import { AuthScreen } from './components/auth/AuthScreen.tsx'
import { RoomSelector } from './components/auth/RoomSelector.tsx'
import { useDialecticSocket } from './hooks/useDialecticSocket.ts'
import { AppLayout } from './components/layout/AppLayout'
import { RoomHeader } from './components/layout/RoomHeader'
import { RoomList } from './components/sidebar/RoomList'
import { RightPanel } from './components/sidebar/RightPanel'
import { MessageList } from './components/chat/MessageList'
import { MessageInput } from './components/chat/MessageInput'
import { ParticipantsBar } from './components/chat/ParticipantsBar'
import { TypingIndicator } from './components/chat/TypingIndicator'

function ChatLayout() {
  const user = useAppStore((s) => s.user);
  const currentRoom = useAppStore((s) => s.currentRoom);
  const currentThread = useAppStore((s) => s.currentThread);
  const threads = useAppStore((s) => s.threads);
  const messages = useAppStore((s) => s.messages);
  const memories = useAppStore((s) => s.memories);
  const typingUsers = useAppStore((s) => s.typingUsers);
  const onlineUsers = useAppStore((s) => s.onlineUsers);
  const roomToken = useAppStore((s) => s.roomToken);
  const setThread = useAppStore((s) => s.setThread);
  const leaveRoom = useAppStore((s) => s.leaveRoom);
  const logout = useAppStore((s) => s.logout);

  const { isConnected, sendMessage } = useDialecticSocket();

  const participants = [
    { id: 'claude', name: 'Claude', isOnline: true, isClaude: true },
    ...onlineUsers.map((u) => ({
      id: u.user_id,
      name: u.display_name,
      isOnline: u.status === 'online',
      isClaude: false,
    })),
  ];

  return (
    <AppLayout
      sidebar={
        <RoomList
          rooms={[]}
          activeRoomId={currentRoom?.id ?? null}
          onRoomSelect={() => leaveRoom()}
          onCreateRoom={() => leaveRoom()}
          userName={user?.display_name ?? 'User'}
          onLogout={logout}
        />
      }
      main={
        <>
          <RoomHeader
            roomName={currentRoom?.name ?? 'Dialectic'}
            threads={threads}
            activeThreadId={currentThread?.id ?? ''}
            onThreadChange={(id) => {
              const t = threads.find((th) => th.id === id);
              if (t) setThread(t);
            }}
            onSettingsClick={() => {}}
            connected={isConnected}
          />
          <ParticipantsBar participants={participants} />
          <MessageList
            messages={messages}
            currentUserId={user?.id ?? null}
          />
          <TypingIndicator typingUsers={typingUsers} />
          <MessageInput
            onSend={(content) => sendMessage(content)}
          />
        </>
      }
      rightPanel={
        <RightPanel
          memories={memories}
          threads={threads}
          activeThreadId={currentThread?.id ?? ''}
          onThreadSelect={(id) => {
            const t = threads.find((th) => th.id === id);
            if (t) setThread(t);
          }}
          onForkThread={() => {}}
          onAddMemory={() => {}}
          roomToken={roomToken ?? ''}
          users={onlineUsers.map((u) => ({
            id: u.user_id,
            name: u.display_name,
            status: u.status,
          }))}
        />
      }
    />
  );
}

function App() {
  const isAuthenticated = useAppStore((s) => s.isAuthenticated);
  const currentRoom = useAppStore((s) => s.currentRoom);

  if (!isAuthenticated) return <AuthScreen />;
  if (!currentRoom) return <RoomSelector />;
  return <ChatLayout />;
}

export default App
