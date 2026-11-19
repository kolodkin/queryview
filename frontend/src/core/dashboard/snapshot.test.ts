import { describe, expect, it } from 'vitest'

import { MAX_SNAPSHOT_CHARS, parseSnapshotResult, snapshotDocument } from './snapshot'

describe('snapshotDocument', () => {
  it('puts the charset and a script-blocking policy ahead of anything the frame sent', () => {
    const doc = snapshotDocument('<html><head></head><body>hi</body></html>', 'sales')
    expect(
      doc.startsWith(
        '<!doctype html><meta charset="utf-8">' +
          '<meta http-equiv="Content-Security-Policy" content="' +
          "script-src 'none'; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'" +
          '">',
      ),
    ).toBe(true)
    expect(doc.endsWith('<html><head></head><body>hi</body></html>')).toBe(true)
  })

  it('neutralizes every http-equiv the frame sent: no refresh, no second policy', () => {
    const doc = snapshotDocument(
      '<meta HTTP-Equiv="refresh" content="0;url=https://example.internal">',
      't',
    )
    expect(doc.match(/http-equiv/gi)).toHaveLength(2) // ours, and the frame's renamed
    expect(doc).toContain('<meta data-http-equiv="refresh"')
    expect(snapshotDocument('<meta http-equiv\n = refresh>', 't')).toContain(
      '<meta data-http-equiv\n = refresh>',
    )
  })

  it('leaves the words http-equiv alone in text', () => {
    expect(snapshotDocument('<td>the http-equiv header</td>', 't')).toContain(
      '<td>the http-equiv header</td>',
    )
  })

  it('escapes the title', () => {
    expect(snapshotDocument('', 'a <b> & c')).toContain('<title>a &lt;b&gt; &amp; c</title>')
  })
})

describe('parseSnapshotResult', () => {
  it('accepts the html and the message forms', () => {
    expect(parseSnapshotResult({ type: 'qv-snapshot-result', html: '<html></html>' })).toEqual({
      html: '<html></html>',
    })
    expect(parseSnapshotResult({ type: 'qv-snapshot-result', message: 'no getHTML' })).toEqual({
      message: 'no getHTML',
    })
  })

  it('rejects other messages, non-strings and an oversize document', () => {
    expect(parseSnapshotResult({ type: 'qv-size', height: 1 })).toBeNull()
    expect(parseSnapshotResult({ type: 'qv-snapshot-result', html: 7 })).toBeNull()
    expect(parseSnapshotResult({ type: 'qv-snapshot-result' })).toBeNull()
    expect(parseSnapshotResult({ type: 'qv-snapshot-result', html: { length: 1 } })).toBeNull()
  })

  it('answers an oversize document with a message, not silence', () => {
    expect(
      parseSnapshotResult({ type: 'qv-snapshot-result', html: 'x'.repeat(MAX_SNAPSHOT_CHARS + 1) }),
    ).toEqual({ message: 'The dashboard is too large to snapshot.' })
  })
})
