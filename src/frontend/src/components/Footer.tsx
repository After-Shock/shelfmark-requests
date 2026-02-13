interface FooterProps {
  debug?: boolean;
  isAdmin?: boolean;
}

export const Footer = ({ debug, isAdmin }: FooterProps) => {
  return (
    <footer
      className="mt-8 py-4"
      style={{
        paddingBottom: 'calc(1rem + env(safe-area-inset-bottom))',
      }}
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex items-baseline justify-center gap-2">
        <span className="text-sm font-medium opacity-70">
          Sullyflix Inc
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
