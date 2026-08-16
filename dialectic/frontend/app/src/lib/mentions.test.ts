import { describe, expect, it } from 'vitest'
import { addressBlock, classifyMention, decorateMentions } from './mentions'

const ROOM = { names: ['Amo', 'Dan', 'Scott'], selfName: 'Amo' }

function html(markup: string): string {
  return decorateMentions(markup, ROOM)
}

describe('classifyMention', () => {
  it('reads the participant by any of its aliases', () => {
    for (const alias of ['dialectic', 'Claude', 'LLM']) {
      expect(classifyMention(alias, ROOM)?.kind).toBe('participant')
    }
  })

  it('treats a handle STARTING with an alias as the participant', () => {
    // Real message, 2026-08-15: "@amo @llmThe oil futures curve just split".
    // Misparsing toward speech is the safe direction on the server, and the
    // same handle must not paint as a stranger here.
    expect(classifyMention('llmThe', ROOM)?.kind).toBe('participant')
  })

  it('distinguishes the reader from the other humans', () => {
    expect(classifyMention('amo', ROOM)?.kind).toBe('self')
    expect(classifyMention('dan', ROOM)?.kind).toBe('human')
    expect(classifyMention('scott', ROOM)?.kind).toBe('human')
  })

  it('leaves an unknown handle unresolved', () => {
    // Painting a mention for somebody who is not here tells the reader an
    // address happened that did not.
    expect(classifyMention('nobody', ROOM)).toBeNull()
  })

  it('does not let a longer handle claim a name', () => {
    expect(classifyMention('danw', ROOM)).toBeNull()
  })
})

describe('decorateMentions', () => {
  it('wraps a human mention with its kind', () => {
    const out = html('<p>@dan what do you think?</p>')
    expect(out).toContain('class="mention mention-human"')
    expect(out).toContain('@dan')
  })

  it('gives the reader their own class', () => {
    expect(html('<p>@amo look at this</p>')).toContain('mention-self')
  })

  it('gives the participant a different one', () => {
    expect(html('<p>@dialectic what do you think?</p>')).toContain('mention-participant')
  })

  it('decorates every mention in one message', () => {
    // The message that started this: an ask to Amo that names the participant.
    const out = html(
      '<p>@amo feature idea can you make it highlight the name if it is one ' +
        'of us and make the @llm a different color</p>',
    )
    expect(out).toContain('mention-self')
    expect(out).toContain('mention-participant')
  })

  it('leaves an email alone', () => {
    const out = html('<p>write to amo@dialectic.example about it</p>')
    expect(out).not.toContain('<span')
  })

  it('leaves an unresolvable handle as plain text', () => {
    expect(html('<p>@nobody are you there</p>')).not.toContain('<span')
  })

  it('does not decorate inside code', () => {
    const out = html('<p>run <code>curl @dan</code> first</p>')
    expect(out).not.toContain('<span')
  })

  it('does not decorate inside a link', () => {
    const out = html('<p><a href="https://x.test">ask @dan</a></p>')
    expect(out).not.toContain('<span')
  })

  it('preserves surrounding text exactly', () => {
    const out = html('<p>hey @dan and @scott, thoughts?</p>')
    expect(out).toContain('hey ')
    expect(out).toContain(' and ')
    expect(out).toContain(', thoughts?')
  })

  it('cannot introduce markup from the message body', () => {
    // The handle is written into textContent, never interpolated into HTML.
    const out = decorateMentions('<p>@dan</p>', {
      names: ['<img src=x onerror=alert(1)>', 'Dan'],
      selfName: null,
    })
    expect(out).not.toContain('onerror')
    expect(out).toContain('mention-human')
  })

  it('is a no-op on content with no @ at all', () => {
    const markup = '<p>nothing to see</p>'
    expect(decorateMentions(markup, ROOM)).toBe(markup)
  })
})

describe('addressBlock', () => {
  it('reads the leading run of handles', () => {
    expect(addressBlock('@dan @scott what do you both think?', ROOM)).toEqual(['Dan', 'Scott'])
  })

  it('is empty when the message does not open with an address', () => {
    expect(addressBlock('hey @dan what do you think?', ROOM)).toEqual([])
  })

  it('stops at the first non-handle word', () => {
    // "@amo feature idea ... @llm ..." addresses Amo; @llm is the subject.
    const block = addressBlock(
      '@amo feature idea can you make it highlight the name and the @llm color',
      ROOM,
    )
    expect(block).toEqual(['Amo'])
  })

  it('includes the participant when the address names it', () => {
    expect(addressBlock('@dan @dialectic thoughts?', ROOM)).toEqual(['Dan', 'Dialectic'])
  })

  it('ignores an unresolvable handle', () => {
    expect(addressBlock('@nobody hello', ROOM)).toEqual([])
  })
})
