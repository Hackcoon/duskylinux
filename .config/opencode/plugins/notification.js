import { execFile } from "node:child_process"

function notify(title, body) {
  return new Promise((resolve) => {
    execFile("notify-send", [title, body], (error) => {
      if (error) console.error(`[notification] notify-send failed: ${error.message}`)
      resolve()
    })
  })
}

export default {
  id: "notification",
  setup(ctx) {
    const controller = new AbortController()

    void (async () => {
      try {
        for await (const event of ctx.event.subscribe({ signal: controller.signal })) {
          if (event.type === "session.idle") {
            await notify("OpenCode", "Session completed!")
          }
        }
      } catch (error) {
        if (error?.name !== "AbortError") console.error(`[notification] event stream failed: ${error}`)
      }
    })()

    return () => controller.abort()
  },
}
