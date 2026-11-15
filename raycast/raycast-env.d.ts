/// <reference types="@raycast/api">

/* 🚧 🚧 🚧
 * This file is auto-generated from the extension's manifest.
 * Do not modify manually. Instead, update the `package.json` file.
 * 🚧 🚧 🚧 */

/* eslint-disable @typescript-eslint/ban-types */

type ExtensionPreferences = {}

/** Preferences accessible in all the extension's commands */
declare type Preferences = ExtensionPreferences

declare namespace Preferences {
  /** Preferences accessible in the `tasks` command */
  export type Tasks = ExtensionPreferences & {}
  /** Preferences accessible in the `new-task` command */
  export type NewTask = ExtensionPreferences & {}
}

declare namespace Arguments {
  /** Arguments passed to the `tasks` command */
  export type Tasks = {}
  /** Arguments passed to the `new-task` command */
  export type NewTask = {}
}

