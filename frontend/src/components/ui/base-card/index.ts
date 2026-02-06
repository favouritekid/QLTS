// src/components/ui/base-card/index.ts
/**
 * BaseCard System - Standardized Mobile Card Components
 *
 * This system provides a consistent layout for all mobile data cards.
 * Use these components for list item cards that need:
 * - Checkbox selection
 * - Action menu (⋮)
 * - Status badges
 * - Metadata display
 *
 * Structure: Header → Body → Meta → Actions
 *
 * @example
 * ```tsx
 * <BaseCard selected={isSelected} onSelect={handleSelect}>
 *   <CardHeader
 *     title="Nguyễn Văn A"
 *     subtitle="Lead #123"
 *     badge={<Badge>Hot</Badge>}
 *   />
 *   <CardBody>
 *     <CardField label="Email" value="user@example.com" />
 *     <CardField label="Phone" value="0901234567" />
 *   </CardBody>
 *   <CardMeta>
 *     <Badge variant="success">Active</Badge>
 *     <CardTime date={createdAt} />
 *   </CardMeta>
 *   <CardActions>
 *     <DropdownMenu>...</DropdownMenu>
 *   </CardActions>
 * </BaseCard>
 * ```
 */

export { BaseCard } from "./BaseCard"
export { CardHeader } from "./CardHeader"
export { CardBody, CardField, CardFieldRow } from "./CardBody"
export { CardMeta, CardTime } from "./CardMeta"
export { CardActions } from "./CardActions"

// Re-export types
export type { BaseCardProps } from "./BaseCard"
export type { CardHeaderProps } from "./CardHeader"
export type { CardBodyProps, CardFieldProps, CardFieldRowProps } from "./CardBody"
export type { CardMetaProps, CardTimeProps } from "./CardMeta"
export type { CardActionsProps } from "./CardActions"
