import { Node, mergeAttributes } from '@tiptap/core';
import { ReactNodeViewRenderer, NodeViewWrapper, type NodeViewProps } from '@tiptap/react';
import type { CommandProps } from '@tiptap/core';

function DomTagComponent({ node }: NodeViewProps) {
  const tagName = (node.attrs as any).tagName as string;
  const sectionId = (node.attrs as any).sectionId as string;
  const displayLabel = sectionId || tagName;
  return (
    <NodeViewWrapper as="span" className="dom-tag-wrapper" draggable={false}>
      <span className="dom-tag-capsule" contentEditable={false} data-tag-name={tagName} data-section-id={sectionId}>
        ✨ {displayLabel}
      </span>
    </NodeViewWrapper>
  );
}

export const DomTag = Node.create({
  name: 'domTag',
  group: 'inline',
  inline: true,
  atom: true,

  addAttributes() {
    return {
      tagName: {
        default: 'div',
      },
      sectionId: {
        default: '',
      },
      textContent: {
        default: '',
      },
    };
  },

  parseHTML() {
    return [{ tag: 'span[data-dom-tag]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return ['span', mergeAttributes(HTMLAttributes, { 'data-dom-tag': '' })];
  },

  addNodeView() {
    return ReactNodeViewRenderer(DomTagComponent);
  },

  addCommands() {
    return {
      insertDomTag:
        (tagName: string, sectionId?: string, textContent?: string) =>
        ({ commands }: CommandProps) => {
          return commands.insertContent({ type: this.name, attrs: { tagName, sectionId: sectionId || '', textContent: textContent || '' } });
        },
    };
  },
});

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    domTag: {
      insertDomTag: (tagName: string, sectionId?: string, textContent?: string) => ReturnType;
    };
  }
}
