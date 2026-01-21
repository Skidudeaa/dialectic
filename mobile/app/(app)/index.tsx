import { View, Text, StyleSheet, Pressable } from 'react-native';
import { useSession } from '@/contexts/session-context';
import { logout } from '@/services/auth';
import { useThemeColor } from '@/hooks/use-theme-color';

export default function HomeScreen() {
  const { session, signOut } = useSession();
  const textColor = useThemeColor({}, 'text');
  const backgroundColor = useThemeColor({}, 'background');

  const handleLogout = async () => {
    await logout();
    await signOut();
  };

  return (
    <View style={[styles.container, { backgroundColor }]}>
      <View style={styles.content}>
        <Text style={[styles.title, { color: textColor }]}>Welcome to Dialectic</Text>
        <Text style={[styles.subtitle, { color: textColor }]}>
          Logged in as {session?.user.email}
        </Text>
        <Text style={[styles.verifiedBadge]}>
          Email verified
        </Text>
      </View>

      <Pressable style={styles.logoutButton} onPress={handleLogout}>
        <Text style={styles.logoutText}>Sign Out</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: 24,
  },
  content: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  title: {
    fontSize: 24,
    fontWeight: '700',
    marginBottom: 8,
  },
  subtitle: {
    fontSize: 16,
    opacity: 0.7,
    marginBottom: 16,
  },
  verifiedBadge: {
    backgroundColor: '#22c55e',
    color: '#ffffff',
    paddingHorizontal: 12,
    paddingVertical: 4,
    borderRadius: 12,
    fontSize: 12,
    fontWeight: '600',
    overflow: 'hidden',
  },
  logoutButton: {
    backgroundColor: '#ef4444',
    padding: 16,
    borderRadius: 8,
    alignItems: 'center',
  },
  logoutText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
  },
});
