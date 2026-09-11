declare namespace JSX {
  interface IntrinsicElements {
    webview: React.DetailedHTMLProps<
      React.HTMLAttributes<HTMLElement> & {
        src?: string;
        style?: React.CSSProperties;
        partition?: string;
      },
      HTMLElement
    >;
  }
}
