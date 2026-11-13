CREATE TABLE `api_rate_limits` (
	`id` text PRIMARY KEY NOT NULL,
	`owner_id` text NOT NULL,
	`action` text NOT NULL,
	`window_start` integer NOT NULL,
	`request_count` integer DEFAULT 1 NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `api_rate_limits_owner_action_window_uq` ON `api_rate_limits` (`owner_id`,`action`,`window_start`);--> statement-breakpoint
ALTER TABLE `documents` ADD `owner_id` text;--> statement-breakpoint
ALTER TABLE `documents` ADD `is_synthetic` integer DEFAULT false NOT NULL;--> statement-breakpoint
ALTER TABLE `documents` ADD `input_version` integer DEFAULT 1 NOT NULL;--> statement-breakpoint
ALTER TABLE `documents` ADD `extraction_version` integer DEFAULT 0 NOT NULL;--> statement-breakpoint
ALTER TABLE `extraction_runs` ADD `input_version` integer DEFAULT 1 NOT NULL;--> statement-breakpoint
ALTER TABLE `extraction_runs` ADD `input_hash` text DEFAULT '' NOT NULL;--> statement-breakpoint
ALTER TABLE `extraction_runs` ADD `mode` text DEFAULT 'llm_assisted' NOT NULL;--> statement-breakpoint
ALTER TABLE `extraction_runs` ADD `status` text DEFAULT 'completed' NOT NULL;--> statement-breakpoint
ALTER TABLE `extraction_runs` ADD `model` text;--> statement-breakpoint
ALTER TABLE `extraction_runs` ADD `provider` text;--> statement-breakpoint
ALTER TABLE `extraction_runs` ADD `error` text;--> statement-breakpoint
UPDATE `documents` SET `is_synthetic` = 1 WHERE `is_demo` = 1;--> statement-breakpoint
UPDATE `documents` SET `extraction_version` = COALESCE((SELECT MAX(`version`) FROM `extraction_runs` WHERE `extraction_runs`.`document_id` = `documents`.`id`), 0);
