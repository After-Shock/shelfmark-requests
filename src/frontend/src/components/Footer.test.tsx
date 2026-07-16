import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { Footer, formatFooterVersion } from './Footer';

describe('formatFooterVersion', () => {
  it('formats a semantic version', () => {
    expect(formatFooterVersion('1.6.0')).toBe('v1.6.0');
  });

  it.each([undefined, '', 'N/A', '1.06', 'v1.6.0'])('hides invalid value %s', (value) => {
    expect(formatFooterVersion(value)).toBeNull();
  });
});

describe('Footer', () => {
  it('renders the company and release version', () => {
    const html = renderToStaticMarkup(<Footer version="1.6.0" />);
    expect(html).toContain('Sullyflix Inc');
    expect(html).toContain('·');
    expect(html).toContain('v1.6.0');
  });

  it('omits the separator and version when unavailable', () => {
    const html = renderToStaticMarkup(<Footer version="N/A" />);
    expect(html).toContain('Sullyflix Inc');
    expect(html).not.toContain('·');
    expect(html).not.toContain('vN/A');
  });

  it('preserves the admin debug badge', () => {
    const html = renderToStaticMarkup(<Footer version="1.6.0" debug isAdmin />);
    expect(html).toContain('Debug');
  });
});
