interface FooterProps {
  debug?: boolean;
  isAdmin?: boolean;
  version?: string;
}

const SEMANTIC_VERSION = /^[0-9]+\.[0-9]+\.[0-9]+$/;

export const formatFooterVersion = (version?: string): string | null => {
  const normalized = version?.trim();
  return normalized && SEMANTIC_VERSION.test(normalized) ? `v${normalized}` : null;
};

export const Footer = ({ debug, isAdmin, version }: FooterProps) => {
  const displayVersion = formatFooterVersion(version);

  return (
    <footer
      className="mt-8 py-4"
      style={{
        paddingBottom: 'calc(1rem + env(safe-area-inset-bottom))',
      }}
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex items-baseline justify-center gap-2">
        <span className="text-sm font-medium opacity-70">
          Sullyflix Inc{displayVersion && <> · {displayVersion}</>}
        </span>
        {debug && isAdmin && (
          <span className="text-xs px-1.5 py-0.5 rounded opacity-60" style={{ background: 'var(--border-muted)' }}>
            Debug
          </span>
        )}
      </div>
    </footer>
  );
};
