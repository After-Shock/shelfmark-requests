import { ReactNode } from 'react';
import * as RadixTooltip from '@radix-ui/react-tooltip';

interface TooltipProps {
  content: ReactNode;
  children: ReactNode;
  position?: 'top' | 'bottom' | 'left' | 'right';
  delay?: number;
  className?: string;
}

export function Tooltip({
  content,
  children,
  position = 'top',
  delay = 200,
  className = '',
}: TooltipProps) {
  if (!content) {
    return <>{children}</>;
  }

  return (
    <RadixTooltip.Provider delayDuration={delay}>
      <RadixTooltip.Root>
        <RadixTooltip.Trigger asChild>
          <div className="inline-flex">{children}</div>
        </RadixTooltip.Trigger>
        <RadixTooltip.Portal>
          <RadixTooltip.Content
            side={position}
            sideOffset={8}
            collisionPadding={8}
            className={`z-[9999] px-3 py-2 text-xs rounded-lg shadow-lg animate-fade-in ${className}`}
            style={{
              background: 'var(--bg-soft)',
              color: 'var(--text)',
              border: '1px solid var(--border-muted)',
            }}
          >
            {content}
          </RadixTooltip.Content>
        </RadixTooltip.Portal>
      </RadixTooltip.Root>
    </RadixTooltip.Provider>
  );
}

export default Tooltip;
