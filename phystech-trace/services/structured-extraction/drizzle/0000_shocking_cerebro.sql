CREATE TABLE `documents` (
	`id` text PRIMARY KEY NOT NULL,
	`title` text NOT NULL,
	`file_name` text NOT NULL,
	`format` text NOT NULL,
	`is_demo` integer DEFAULT false NOT NULL,
	`parser_json` text NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`updated_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`last_extraction_id` text
);
--> statement-breakpoint
CREATE TABLE `extraction_runs` (
	`id` text PRIMARY KEY NOT NULL,
	`document_id` text NOT NULL,
	`version` integer NOT NULL,
	`document_type` text NOT NULL,
	`schema_version` text NOT NULL,
	`payload` text NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`document_id`) REFERENCES `documents`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `extraction_runs_document_version_uq` ON `extraction_runs` (`document_id`,`version`);--> statement-breakpoint
CREATE INDEX `extraction_runs_document_idx` ON `extraction_runs` (`document_id`,`created_at`);