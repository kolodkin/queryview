import { describe, expect, it } from 'vitest'

import { MAX_SNAPSHOT_BYTES, parseSnapshotResult, snapshotDocument } from './snapshot'

describe('snapshotDocument', () => {
  it('puts the charset and a script-blocking policy ahead of anything the frame sent', () => {
    const doc = snapshotDocument('<html><head></head><body>hi</body></html>', 'sales')
    expect(
      doc.startsWith(
        '<!doctype html><meta charset="utf-8">' +
          '<meta http-equiv="Content-Security-Policy" content="' +
          "script-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'" +
          '">',
      ),
    ).toBe(true)
    expect(doc.endsWith('<html><head></head><body>hi</body></html>')).toBe(true)
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
    const big = { type: 'qv-snapshot-result', html: { length: MAX_SNAPSHOT_BYTES + 1 } }
    expect(parseSnapshotResult(big)).toBeNull()
    expect(
      parseSnapshotResult({ type: 'qv-snapshot-result', html: 'x'.repeat(MAX_SNAPSHOT_BYTES + 1) }),
    ).toBeNull()
  })
})
