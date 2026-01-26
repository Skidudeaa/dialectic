import React, { useState, ReactNode, useCallback } from 'react';
import { View, Text, StyleSheet, Platform } from 'react-native';

export interface DroppedFile {
  uri: string;
  name: string;
  type: string;
}

interface DropZoneProps {
  children: ReactNode;
  onDrop: (files: DroppedFile[]) => void;
  /** Show visual feedback when dragging */
  showFeedback?: boolean;
  /** Custom feedback text */
  feedbackText?: string;
}

/**
 * Drag-and-drop zone for desktop file attachments.
 *
 * ARCHITECTURE: Drag-drop wrapper for desktop file handling.
 * WHY: Desktop users expect drag-and-drop for file attachments.
 * TRADEOFF: Uses DOM events (desktop only); mobile uses image pickers.
 *
 * On desktop: handles drag events and accepts dropped files.
 * On mobile: renders children only (no drag support).
 *
 * @example
 * <DropZone onDrop={handleFilesDropped}>
 *   <ChatView />
 * </DropZone>
 */
export function DropZone({
  children,
  onDrop,
  showFeedback = true,
  feedbackText = 'Drop files to attach',
}: DropZoneProps) {
  const [isDragging, setIsDragging] = useState(false);

  const isDesktop = Platform.OS === 'macos' || Platform.OS === 'windows';

  const handleDragEnter = useCallback((e: any) => {
    e.preventDefault?.();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: any) => {
    e.preventDefault?.();
    setIsDragging(false);
  }, []);

  const handleDragOver = useCallback((e: any) => {
    e.preventDefault?.();
  }, []);

  const handleDrop = useCallback(
    (e: any) => {
      e.preventDefault?.();
      setIsDragging(false);

      // Extract files from drop event
      // macOS: e.nativeEvent.dataTransfer.files
      // Windows: similar but may need different handling
      const dataTransfer = e.nativeEvent?.dataTransfer ?? e.dataTransfer;
      if (!dataTransfer?.files) return;

      const files: DroppedFile[] = [];
      for (let i = 0; i < dataTransfer.files.length; i++) {
        const file = dataTransfer.files[i];
        files.push({
          uri: file.uri || file.path || URL.createObjectURL?.(file) || '',
          name: file.name,
          type: file.type,
        });
      }

      if (files.length > 0) {
        onDrop(files);
      }
    },
    [onDrop]
  );

  if (!isDesktop) {
    return <>{children}</>;
  }

  return (
    <View
      style={styles.container}
      // @ts-ignore - drag events exist on desktop
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {children}

      {showFeedback && isDragging && (
        <View style={styles.feedbackOverlay}>
          <View style={styles.feedbackBox}>
            <Text style={styles.feedbackText}>{feedbackText}</Text>
          </View>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  feedbackOverlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(99, 102, 241, 0.1)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  feedbackBox: {
    backgroundColor: 'white',
    paddingHorizontal: 24,
    paddingVertical: 16,
    borderRadius: 12,
    borderWidth: 2,
    borderColor: '#6366f1',
    borderStyle: 'dashed',
  },
  feedbackText: {
    fontSize: 16,
    color: '#6366f1',
    fontWeight: '600',
  },
});
