import { View, Text, StyleSheet, Pressable } from 'react-native';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { useSession } from '@/contexts/session-context';
import { logout } from '@/services/auth';
import { useThemeColor } from '@/hooks/use-theme-color';

export default function HomeScreen() {
  const router = useRouter();
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

      <View style={styles.buttonRow}>
        <Pressable
          style={styles.settingsButton}
          onPress={() => (router.push as (path: string) => void)('/settings')}
        >
          <Ionicons name="settings-outline" size={20} color="#6366f1" />
          <Text style={styles.settingsText}>Settings</Text>
        </Pressable>

        <Pressable style={styles.logoutButton} onPress={handleLogout}>
          <Text style={styles.logoutText}>Sign Out</Text>
        </Pressable>
      </View>
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
  buttonRow: {
    flexDirection: 'row',
    gap: 12,
  },
  settingsButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#f1f5f9',
    padding: 16,
    borderRadius: 8,
    gap: 8,
  },
  settingsText: {
    color: '#6366f1',
    fontSize: 16,
    fontWeight: '600',
  },
  logoutButton: {
    flex: 1,
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
