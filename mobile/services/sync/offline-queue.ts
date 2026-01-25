/**
 * ARCHITECTURE: MMKV-backed message queue for offline support.
 * WHY: Users should be able to compose while offline (CONTEXT.md).
 * TRADEOFF: Queue size limited to 100 to prevent memory issues.
 */

import { createMMKV, type MMKV } from 'react-native-mmkv';
import { v4 as uuidv4 } from 'uuid';

const storage: MMKV = createMMKV({ id: 'offline-queue' });
const QUEUE_KEY = 'pending_messages';
const MAX_QUEUE_SIZE = 100; // RESEARCH.md: Limit to prevent unbounded growth

export interface QueuedMessage {
  id: string; // Client-generated UUID
  type: 'send_message';
  payload: {
    content: string;
    thread_id: string;
    message_type: string;
    references_message_id?: string;
  };
  timestamp: number;
  status: 'pending' | 'sending' | 'failed';
  retryCount: number;
}

class OfflineQueue {
  private queue: QueuedMessage[] = [];

  constructor() {
    this.loadQueue();
  }

  private loadQueue() {
    try {
      const stored = storage.getString(QUEUE_KEY);
      if (stored) {
        this.queue = JSON.parse(stored);
      }
    } catch (e) {
      console.error('Failed to load offline queue:', e);
      this.queue = [];
    }
  }

  private saveQueue() {
    try {
      storage.set(QUEUE_KEY, JSON.stringify(this.queue));
    } catch (e) {
      console.error('Failed to save offline queue:', e);
    }
  }

  enqueue(
    message: Omit<QueuedMessage, 'id' | 'timestamp' | 'status' | 'retryCount'>
  ): string {
    // Enforce max queue size
    if (this.queue.length >= MAX_QUEUE_SIZE) {
      // Remove oldest message
      this.queue.shift();
    }

    const id = uuidv4();
    const queuedMessage: QueuedMessage = {
      ...message,
      id,
      timestamp: Date.now(),
      status: 'pending',
      retryCount: 0,
    };

    this.queue.push(queuedMessage);
    this.saveQueue();
    return id;
  }

  dequeue(): QueuedMessage | undefined {
    const message = this.queue.find((m) => m.status === 'pending');
    return message;
  }

  markSending(id: string) {
    const msg = this.queue.find((m) => m.id === id);
    if (msg) {
      msg.status = 'sending';
      this.saveQueue();
    }
  }

  markSent(id: string) {
    this.queue = this.queue.filter((m) => m.id !== id);
    this.saveQueue();
  }

  markFailed(id: string) {
    const msg = this.queue.find((m) => m.id === id);
    if (msg) {
      msg.status = 'failed';
      msg.retryCount++;
      this.saveQueue();
    }
  }

  getAll(): QueuedMessage[] {
    return [...this.queue];
  }

  getPending(): QueuedMessage[] {
    return this.queue.filter(
      (m) => m.status === 'pending' || m.status === 'failed'
    );
  }

  getById(id: string): QueuedMessage | undefined {
    return this.queue.find((m) => m.id === id);
  }

  clear() {
    this.queue = [];
    this.saveQueue();
  }

  get length(): number {
    return this.queue.length;
  }
}

export const offlineQueue = new OfflineQueue();
