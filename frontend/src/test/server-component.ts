/**
 * CHỈ cho test: dựng cây phần tử của một TRANG Next (Server Component) như máy chủ dựng — chờ mọi thành phần `async` (vd thành
 * phần con chờ `searchParams` / `params` bên trong `<Suspense>`) rồi trả cây chỉ còn thành phần thường để `render` của Testing
 * Library vẽ được. Mục đích: test đi qua ĐÚNG `page.tsx` (đính chính 2 §3: "test đi qua TRANG"), không chỉ qua thành phần con.
 *
 * Chỉ gọi hàm thành phần `async` (thành phần máy chủ); thành phần thường (có hook) để nguyên cho React vẽ.
 */
import { cloneElement, isValidElement, type ReactElement, type ReactNode } from "react"

type AsyncComponent = (props: unknown) => Promise<ReactNode>

function isAsyncComponent(type: unknown): type is AsyncComponent {
  return typeof type === "function" && Object.prototype.toString.call(type) === "[object AsyncFunction]"
}

export async function resolveServerTree(node: ReactNode): Promise<ReactNode> {
  if (Array.isArray(node)) return Promise.all(node.map((n: ReactNode) => resolveServerTree(n)))
  if (!isValidElement(node)) return node
  const element = node as ReactElement<{ children?: ReactNode }>
  const type: unknown = element.type
  if (isAsyncComponent(type)) return resolveServerTree(await type(element.props))
  const children = element.props.children
  if (children === undefined) return element
  const resolved = await resolveServerTree(children)
  return Array.isArray(resolved) ? cloneElement(element, undefined, ...resolved) : cloneElement(element, undefined, resolved)
}
