export interface MediaStatus {
  session_id: string | null
  state: 'idle' | 'negotiating' | 'connecting' | 'receiving' | 'closed' | 'error'
  connection_state: string
  received_frames: number
  receive_fps: number
  replaced_frames: number
  width: number
  height: number
  size_version: number
  last_frame_id: number | null
  last_frame_age_ms: number | null
  conversion_ms: number | null
  reason: string | null
}

interface Answer {
  session_id: string
  type: 'answer'
  sdp: string
}

async function requireOk(response: Response): Promise<Response> {
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(typeof body?.detail === 'string'
      ? body.detail : `媒体服务请求失败（HTTP ${response.status}）`)
  }
  return response
}

function waitForIce(pc: RTCPeerConnection, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      pc.removeEventListener('icegatheringstatechange', changed)
      signal.removeEventListener('abort', aborted)
      window.clearTimeout(timer)
    }
    const changed = () => {
      if (pc.iceGatheringState === 'complete') {
        cleanup()
        resolve()
      }
    }
    const aborted = () => {
      cleanup()
      reject(new DOMException('媒体连接已取消。', 'AbortError'))
    }
    const timer = window.setTimeout(() => {
      cleanup()
      reject(new Error('浏览器收集连接信息超时，请重新连接。'))
    }, 10000)
    pc.addEventListener('icegatheringstatechange', changed)
    signal.addEventListener('abort', aborted, { once: true })
    if (signal.aborted) aborted()
    else changed()
  })
}

export class MediaConnection {
  readonly id = crypto.randomUUID()
  private readonly pc = new RTCPeerConnection({ iceServers: [] })
  private readonly abort = new AbortController()
  private timer: number | null = null
  private heartbeatAbort: AbortController | null = null
  private stopped = false
  private downloading = false

  constructor(
    private readonly onStatus: (status: MediaStatus) => void,
    private readonly onError: (message: string) => void,
  ) {
    this.pc.onconnectionstatechange = () => {
      if (!this.stopped && ['failed', 'disconnected', 'closed'].includes(this.pc.connectionState)) {
        this.fail('视频连接已中断，已停止向 Python 传输。请重新连接。')
      }
    }
  }

  async start(stream: MediaStream): Promise<void> {
    const timeout = window.setTimeout(() => this.abort.abort(), 30000)
    try {
      const track = stream.getVideoTracks()[0]
      if (!track || track.readyState !== 'live') throw new Error('没有可发送的视频轨道。')
      this.pc.addTransceiver(track, { direction: 'sendonly', streams: [stream] })
      await this.pc.setLocalDescription(await this.pc.createOffer())
      await waitForIce(this.pc, this.abort.signal)
      if (this.stopped) return
      const local = this.pc.localDescription
      if (!local) throw new Error('浏览器没有生成视频连接信息。')
      const response = await requireOk(await fetch('/api/media/offer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: this.id, type: 'offer', sdp: local.sdp }),
        signal: this.abort.signal,
      }))
      const answer = await response.json() as Answer
      if (this.stopped) return
      if (answer.session_id !== this.id || answer.type !== 'answer') {
        throw new Error('媒体应答与当前会话不匹配。')
      }
      await this.pc.setRemoteDescription({ type: answer.type, sdp: answer.sdp })
      if (!this.stopped) void this.heartbeat()
    } catch (cause) {
      if (!this.stopped) {
        this.fail(cause instanceof Error && cause.name === 'AbortError'
          ? '媒体协商超时或已取消，请重新连接。'
          : cause instanceof Error ? cause.message : '无法连接视频接收服务。')
      }
    } finally {
      window.clearTimeout(timeout)
    }
  }

  private async heartbeat() {
    if (this.stopped) return
    const controller = new AbortController()
    this.heartbeatAbort = controller
    const timeout = window.setTimeout(() => controller.abort(), 3000)
    try {
      const response = await requireOk(await fetch(`/api/media/${this.id}/heartbeat`, {
        method: 'POST', signal: controller.signal,
      }))
      const status = await response.json() as MediaStatus
      if (this.stopped) return
      if (status.session_id !== this.id) throw new Error('收到其他会话的状态。')
      this.onStatus(status)
      if (['closed', 'error'].includes(status.state)) {
        this.fail(status.reason || '后端媒体会话已关闭。')
        return
      }
      this.timer = window.setTimeout(() => void this.heartbeat(), 1000)
    } catch (cause) {
      if (!this.stopped) {
        this.fail(cause instanceof Error && cause.name !== 'AbortError'
          ? cause.message : '无法更新后端媒体状态，传输已停止。')
      }
    } finally {
      window.clearTimeout(timeout)
      if (this.heartbeatAbort === controller) this.heartbeatAbort = null
    }
  }

  private fail(message: string) {
    this.onError(message)
    void this.stop()
  }

  async stop(): Promise<void> {
    if (this.stopped) return
    this.stopped = true
    this.abort.abort()
    this.heartbeatAbort?.abort()
    if (this.timer !== null) window.clearTimeout(this.timer)
    this.pc.onconnectionstatechange = null
    this.pc.close()
    try {
      await fetch(`/api/media/${this.id}`, {
        method: 'DELETE', keepalive: true, signal: AbortSignal.timeout(3000),
      })
    } catch {
      // Backend connection/frame/heartbeat timeouts also reclaim abandoned sessions.
    }
  }

  async downloadSnapshot(): Promise<void> {
    if (this.stopped || this.downloading) throw new Error('媒体会话未就绪或正在保存。')
    this.downloading = true
    let url: string | null = null
    try {
      const response = await requireOk(await fetch(`/api/media/${this.id}/snapshot`, {
        cache: 'no-store', signal: AbortSignal.timeout(10000),
      }))
      const image = await response.blob()
      if (this.stopped) throw new Error('会话已停止，截图下载已取消。')
      url = URL.createObjectURL(image)
      const link = document.createElement('a')
      link.href = url
      link.download = `maple-${this.id}-${response.headers.get('X-Frame-Id') || 'frame'}.png`
      document.body.appendChild(link)
      link.click()
      link.remove()
    } finally {
      if (url) {
        const downloadUrl = url
        window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000)
      }
      this.downloading = false
    }
  }
}
